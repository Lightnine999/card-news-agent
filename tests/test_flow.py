"""모의 엔진으로 S0~S5 흐름과 PRD의 핵심 규칙을 확인해요."""

from tests.conftest import rid


def create(client, topic="AI 최신소식", **extra):
    res = client.post("/api/projects", json={"topic": topic, **extra})
    assert res.status_code == 201, res.text
    return res.json()["projectId"]


def get(client, pid):
    res = client.get(f"/api/projects/{pid}")
    assert res.status_code == 200, res.text
    return res.json()


def research(client, pid, request_id=None, **extra):
    return client.post(
        f"/api/projects/{pid}/research",
        json={"requestId": request_id or rid(), **extra},
    )


def to_selecting(client, run_worker, topic="AI 최신소식"):
    pid = create(client, topic)
    assert research(client, pid).status_code == 202
    run_worker()
    return pid, get(client, pid)


def select(client, pid, ids, version):
    return client.post(
        f"/api/projects/{pid}/selection",
        json={"candidateIds": ids, "version": version},
    )


def to_question(client, run_worker, topic="AI 최신소식"):
    pid, p = to_selecting(client, run_worker, topic)
    ids = [c["id"] for c in p["research"]["candidates"][:2]]
    res = select(client, pid, ids, p["version"])
    assert res.status_code == 200, res.text
    res = client.post(
        f"/api/projects/{pid}/deep-research",
        json={"version": res.json()["version"], "requestId": rid()},
    )
    assert res.status_code == 202, res.text
    run_worker()
    return pid, get(client, pid)


def answer(client, pid, q, ans, request_id=None, version=None):
    return client.post(
        f"/api/projects/{pid}/answers",
        json={
            "questionId": q["id"],
            "version": q["version"] if version is None else version,
            "answer": ans,
            "requestId": request_id or rid(),
        },
    )


# --- S0·S1: 주제 입력과 넓은 조사 -------------------------------------------


def test_research_shows_candidates_period_and_mock_flag(client, run_worker):
    pid, p = to_selecting(client, run_worker)
    assert p["stage"] == "selecting"
    assert p["isMock"] is True
    assert p["research"]["period"]["days"] == 7
    assert p["research"]["requestedAt"]
    cands = p["research"]["candidates"]
    assert 7 <= len(cands) <= 12
    assert any(c["dateStatus"] == "unverified" and c["publishedAt"] is None for c in cands)
    assert any(len(c["sources"]) > 1 for c in cands)  # 같은 발표 기사 묶음
    assert p["lastRun"]["status"] == "succeeded"


def test_topic_is_validated(client):
    assert client.post("/api/projects", json={"topic": "   "}).status_code == 422
    body = client.post("/api/projects", json={"topic": "x" * 101}).json()
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_same_request_id_returns_same_run(client):
    pid = create(client)
    key = rid()
    first = research(client, pid, key)
    second = research(client, pid, key)
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()


def test_same_request_id_with_different_body_conflicts(client):
    pid = create(client)
    key = rid()
    assert research(client, pid, key).status_code == 202
    res = research(client, pid, key, periodDays=30)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_second_research_while_running_is_rejected(client):
    pid = create(client)
    first = research(client, pid).json()
    res = research(client, pid)
    assert res.status_code == 409
    err = res.json()["error"]
    assert err["code"] == "RUN_IN_PROGRESS"
    assert err["details"]["runId"] == first["runId"]


def test_few_results_ask_to_expand_period(client, run_worker):
    pid = create(client, "적음 테스트")
    research(client, pid)
    run_worker()
    p = get(client, pid)
    q = p["currentQuestion"]
    assert q["id"] == "q_expand_period"
    assert p["activeRun"]["status"] == "waiting_for_user"
    assert answer(client, pid, q, {"optionId": "expand"}).status_code == 202
    run_worker()
    p = get(client, pid)
    assert p["research"]["period"]["days"] == 30
    assert p["stage"] == "selecting"


def test_keep_period_goes_to_selection(client, run_worker):
    pid = create(client, "적음 테스트")
    research(client, pid)
    run_worker()
    q = get(client, pid)["currentQuestion"]
    answer(client, pid, q, {"optionId": "keep"})
    p = get(client, pid)
    assert p["stage"] == "selecting"
    assert p["research"]["period"]["days"] == 7
    assert p["currentQuestion"] is None


def test_search_failure_is_reported_with_retry(client, run_worker):
    pid = create(client, "실패 테스트")
    research(client, pid)
    run_worker()
    p = get(client, pid)
    assert p["lastRun"]["status"] == "failed"
    assert p["lastRun"]["error"]["code"] == "SEARCH_FAILED"
    assert "retry" in p["lastRun"]["error"]["nextActions"]
    # 다시 조사할 수 있어요
    assert research(client, pid).status_code == 202


# --- S2: 후보 선택 -----------------------------------------------------------


def test_selection_is_saved_and_survives_reload(client, run_worker):
    pid, p = to_selecting(client, run_worker)
    ids = [c["id"] for c in p["research"]["candidates"][:2]]
    res = select(client, pid, ids, p["version"])
    assert res.status_code == 200
    assert get(client, pid)["selection"]["candidateIds"] == ids


def test_selection_rejects_more_than_three_and_unknown_ids(client, run_worker):
    pid, p = to_selecting(client, run_worker)
    ids = [c["id"] for c in p["research"]["candidates"][:4]]
    assert select(client, pid, ids, p["version"]).status_code == 422
    assert select(client, pid, ["cand_nope"], p["version"]).status_code == 422


def test_stale_version_is_rejected(client, run_worker):
    pid, p = to_selecting(client, run_worker)
    ids = [p["research"]["candidates"][0]["id"]]
    assert select(client, pid, ids, p["version"]).status_code == 200
    res = select(client, pid, ids, p["version"])  # 예전 버전으로 다시 저장
    assert res.status_code == 409
    err = res.json()["error"]
    assert err["code"] == "VERSION_CONFLICT"
    assert err["details"]["currentVersion"] == p["version"] + 1


def test_deep_research_needs_selection(client, run_worker):
    pid, p = to_selecting(client, run_worker)
    res = client.post(
        f"/api/projects/{pid}/deep-research",
        json={"version": p["version"], "requestId": rid()},
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "STAGE_CONFLICT"


def test_nothing_is_produced_before_selection(client, run_worker):
    pid, p = to_selecting(client, run_worker)
    assert p["storyboard"] is None and p["result"] is None
    res = client.post(
        f"/api/projects/{pid}/approve",
        json={"stage": "storyboard", "version": 1, "requestId": rid()},
    )
    assert res.json()["error"]["code"] == "STAGE_CONFLICT"


# --- S3·S4: 심층 조사와 질문 ---------------------------------------------------


def test_deep_research_waits_for_audience_question(client, run_worker):
    pid, p = to_question(client, run_worker)
    q = p["currentQuestion"]
    assert q["id"] == "q_audience"
    assert q["recommendedOptionId"] and q["recommendationReason"]
    assert q["allowFreeText"] is True
    assert p["activeRun"]["status"] == "waiting_for_user"
    assert p["answers"] == []  # 추천은 답이 아니에요
    assert {n["candidateId"] for n in p["researchNotes"]} == set(p["selection"]["candidateIds"])


def test_answer_continues_to_storyboard(client, run_worker):
    pid, p = to_question(client, run_worker)
    res = answer(client, pid, p["currentQuestion"], {"optionId": "dev"})
    assert res.status_code == 202
    assert res.json()["accepted"] is True
    run_worker()
    p = get(client, pid)
    assert p["stage"] == "storyboard_review"
    assert p["editorial"]["audience"] == "개발자"
    assert p["editorial"]["decidedBy"] == "user_answer"
    assert 5 <= len(p["storyboard"]["cards"]) <= 8
    assert p["currentQuestion"] is None
    assert len(p["answers"]) == 1


def test_free_text_answer_is_accepted(client, run_worker):
    pid, p = to_question(client, run_worker)
    assert answer(client, pid, p["currentQuestion"], {"freeText": "고등학생"}).status_code == 202
    run_worker()
    assert get(client, pid)["editorial"]["audience"] == "고등학생"


def test_double_submit_with_same_request_id_is_applied_once(client, run_worker):
    pid, p = to_question(client, run_worker)
    q, key = p["currentQuestion"], rid()
    first = answer(client, pid, q, {"optionId": "dev"}, key)
    second = answer(client, pid, q, {"optionId": "dev"}, key)
    assert first.json() == second.json()
    run_worker()
    assert len(get(client, pid)["answers"]) == 1


def test_second_answer_from_another_click_is_rejected(client, run_worker):
    pid, p = to_question(client, run_worker)
    q = p["currentQuestion"]
    answer(client, pid, q, {"optionId": "dev"})
    res = answer(client, pid, q, {"optionId": "edu"})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "ALREADY_ANSWERED"


def test_stale_question_version_is_rejected(client, run_worker):
    pid, p = to_question(client, run_worker)
    res = answer(client, pid, p["currentQuestion"], {"optionId": "dev"}, version=99)
    assert res.json()["error"]["code"] == "QUESTION_STALE"


def test_invalid_option_is_rejected(client, run_worker):
    pid, p = to_question(client, run_worker)
    res = answer(client, pid, p["currentQuestion"], {"optionId": "nope"})
    assert res.status_code == 422


def test_projects_do_not_share_sessions_or_questions(client, run_worker):
    a, pa = to_question(client, run_worker, "주제 A")
    b, pb = to_question(client, run_worker, "주제 B")
    assert pa["engine"]["sessionId"] != pb["engine"]["sessionId"]
    # B 화면에서 A의 질문에 답하는 건 거절돼요 (같은 ID여도 프로젝트가 달라요)
    res = answer(client, b, {**pa["currentQuestion"], "version": 2}, {"optionId": "dev"})
    assert res.json()["error"]["code"] == "QUESTION_STALE"
    answer(client, a, pa["currentQuestion"], {"optionId": "dev"})
    run_worker()
    assert get(client, a)["stage"] == "storyboard_review"
    assert get(client, b)["stage"] == "editing"  # B는 여전히 질문 대기


# --- S5: 스토리보드 ------------------------------------------------------------


def to_storyboard(client, run_worker):
    pid, p = to_question(client, run_worker)
    answer(client, pid, p["currentQuestion"], {"optionId": "dev"})
    run_worker()
    return pid, get(client, pid)


def test_storyboard_feedback_makes_new_version(client, run_worker):
    pid, p = to_storyboard(client, run_worker)
    v = p["storyboard"]["version"]
    res = client.post(
        f"/api/projects/{pid}/storyboard/feedback",
        json={"instruction": "표지를 더 짧게", "version": v, "requestId": rid()},
    )
    assert res.status_code == 202
    run_worker()
    p = get(client, pid)
    assert p["storyboard"]["version"] == v + 1
    assert p["stage"] == "storyboard_review"


def test_storyboard_approval_starts_image_production(client, run_worker):
    pid, p = to_storyboard(client, run_worker)
    res = client.post(
        f"/api/projects/{pid}/approve",
        json={"stage": "storyboard", "version": p["storyboard"]["version"], "requestId": rid()},
    )
    assert res.status_code == 202
    run_worker()
    p = get(client, pid)
    assert p["storyboard"]["approvedAt"]
    assert p["stage"] == "reviewing"  # 모든 카드에 글자까지 올리면 검수 단계로
    assert p["lastRun"]["status"] == "succeeded"
    # 모의 엔진 프로젝트는 agy 대신 모의 그림을 써요.
    assert {c["status"] for c in p["result"]["cards"]} == {"done"}
    assert p["result"]["cards"][0]["image"]["origin"] == "mock"
    assert p["result"]["cards"][0]["pngUrl"].endswith("results/cards/card_1.v1.png")


def test_storyboard_approval_with_old_version_is_rejected(client, run_worker):
    pid, p = to_storyboard(client, run_worker)
    res = client.post(
        f"/api/projects/{pid}/approve",
        json={"stage": "storyboard", "version": 0, "requestId": rid()},
    )
    assert res.json()["error"]["code"] == "VERSION_CONFLICT"


# --- 취소·재시작 복구 ----------------------------------------------------------


def test_cancel_waiting_run_restores_selection_stage(client, run_worker):
    pid, p = to_question(client, run_worker)
    run_id = p["activeRun"]["id"]
    res = client.post(f"/api/runs/{run_id}/cancel")
    assert res.json()["status"] == "cancelled"
    p = get(client, pid)
    assert p["activeRun"] is None
    assert p["currentQuestion"] is None
    assert p["stage"] == "selecting"
    # 취소된 질문에 답하면 거절돼요
    assert client.post(f"/api/runs/{run_id}/cancel").json()["status"] == "cancelled"


def test_interrupted_run_can_be_restarted(client, run_worker):
    from cardnews import db, worker

    pid = create(client)
    run_id = research(client, pid).json()["runId"]
    # 작업 프로세스가 가져간 뒤 서버가 죽은 상황을 만들어요
    with db.transaction() as conn:
        conn.execute("UPDATE runs SET status='running', dispatch=0 WHERE id=?", (run_id,))
    worker.recover_interrupted()
    p = get(client, pid)
    assert p["lastRun"]["status"] == "interrupted"
    assert p["lastRun"]["error"]["code"] == "INTERRUPTED"
    res = client.post(f"/api/runs/{run_id}/resume", json={"mode": "restart", "requestId": rid()})
    assert res.status_code == 202, res.text
    run_worker()
    assert get(client, pid)["stage"] == "selecting"


def test_continue_needs_engine_session(client):
    from cardnews import db, worker

    pid = create(client)
    run_id = research(client, pid).json()["runId"]
    with db.transaction() as conn:
        conn.execute("UPDATE runs SET status='running', dispatch=0 WHERE id=?", (run_id,))
    worker.recover_interrupted()
    res = client.post(f"/api/runs/{run_id}/resume", json={"mode": "continue", "requestId": rid()})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "STAGE_CONFLICT"


def test_screen_files_are_revalidated(client):
    assert client.get("/static/views.js").headers["cache-control"] == "no-cache"
    assert client.get("/").headers["cache-control"] == "no-cache"


def test_health_reports_tools(client):
    body = client.get("/api/health").json()
    assert set(body) >= {"claude", "agy", "chromium", "font", "engine"}
    assert body["engine"] == "mock"


def test_mock_out_of_period_candidate_is_excluded(client, run_worker):
    _, p = to_selecting(client, run_worker, "기간밖 테스트")
    assert len(p["research"]["excluded"]) == 1
    assert len(p["research"]["candidates"]) == 8
    assert p["stage"] == "selecting"


def test_expand_question_counts_after_exclusion(client, run_worker):
    pid = create(client, "적음 기간밖 테스트")
    research(client, pid)
    run_worker()
    q = get(client, pid)["currentQuestion"]
    assert q["id"] == "q_expand_period"
    assert "3개" in q["prompt"]  # 뺀 뒤 남은 개수로 물어요


def test_storyboard_cards_have_body_and_image_role(client, run_worker):
    _, p = to_storyboard(client, run_worker)
    cards = p["storyboard"]["cards"]
    assert 5 <= len(cards) <= 8
    assert all(c["keyLine"] and c["body"] and c["imageRole"] and c["sourceUrls"] for c in cards)
