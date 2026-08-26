"""API 端点 URL 与参数常量契约测试。"""

from src.utils.api.api import (
    ANN_LIST_URL,
    BBS_SIGN_URL,
    GAME_SIGN_URL,
    GET_POST_DETAIL_URL,
    GET_POST_LIST_URL,
    GET_TASK_PROCESS_URL,
    HAVE_SIGN_IN_URL,
    ITEM_WEEKLY_REPORT_URL,
    LIKE_POST_URL,
    MAIN_URL,
    REPLY_POST_URL,
    SHARE_POST_URL,
    SHORT_NOTE_URL,
    SIGN_CALENDAR_URL,
)


def test_api_endpoints_match_upstream_contract():
    """验证所有 API 端点常量与 upstream (GsCore DNAUID) 一致。"""
    assert SHORT_NOTE_URL == f"{MAIN_URL}/role/getShortNoteInfo"
    assert ITEM_WEEKLY_REPORT_URL == f"{MAIN_URL}/role/getItemWeeklyReport"
    assert SIGN_CALENDAR_URL == f"{MAIN_URL}/encourage/signin/show"
    assert GAME_SIGN_URL == f"{MAIN_URL}/encourage/signin/signin"
    assert BBS_SIGN_URL == f"{MAIN_URL}/user/signIn"
    assert HAVE_SIGN_IN_URL == f"{MAIN_URL}/user/haveSignInNew"
    assert GET_TASK_PROCESS_URL == f"{MAIN_URL}/encourage/level/getTaskProcess"
    assert GET_POST_LIST_URL == f"{MAIN_URL}/forum/list"
    assert GET_POST_DETAIL_URL == f"{MAIN_URL}/forum/getPostDetail"
    assert LIKE_POST_URL == f"{MAIN_URL}/forum/like"
    assert SHARE_POST_URL == f"{MAIN_URL}/encourage/level/shareTask"
    assert REPLY_POST_URL == f"{MAIN_URL}/forum/comment/createComment"
    assert ANN_LIST_URL == f"{MAIN_URL}/user/mine"
