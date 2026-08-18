from ...infrastructure.config.settings import DNAConfig


def get_main_url():
    try:
        dna_url_proxy = DNAConfig.get_config("DNAUrlProxyUrl").data
    except KeyError:
        dna_url_proxy = ""
    return dna_url_proxy or "https://dnabbs-api.yingxiong.com"


MAIN_URL = get_main_url()
LOGIN_URL = f"{MAIN_URL}/user/sdkLogin"
GET_RSA_PUBLIC_KEY_URL = f"{MAIN_URL}/config/getRsaPublicKey"
GET_SMS_CODE_URL = f"{MAIN_URL}/user/getSmsCode"
LOGIN_LOG_URL = f"{MAIN_URL}/user/login/log"
ROLE_LIST_URL = f"{MAIN_URL}/role/list"
ROLE_FOR_TOOL_URL = f"{MAIN_URL}/role/defaultRoleForTool"
DAMAGE_CONFIG_URL = f"{MAIN_URL}/role/build/config"
DAMAGE_CALCULATE_URL = f"{MAIN_URL}/role/build/calculate"
DAMAGE_WEAPON_URL = f"{MAIN_URL}/role/build/calculateWeapon"
DAMAGE_ENVIRONMENT_URL = f"{MAIN_URL}/role/build/calculateEnvironment"
# role detail
ROLE_DETAIL_URL = f"{MAIN_URL}/role/getCharDetail"
# weapon detail
WEAPON_DETAIL_URL = f"{MAIN_URL}/role/getWeaponDetail"
# refresh token
REFRESH_TOKEN_URL = f"{MAIN_URL}/user/refreshToken"

# task / sign
GET_TASK_PROCESS_URL = f"{MAIN_URL}/task/taskProcess"
TASK_PROCESS_URL = f"{MAIN_URL}/task/taskProcess"
DO_TASK_URL = f"{MAIN_URL}/task/doTask"
GET_REWARD_URL = f"{MAIN_URL}/task/getReward"
BBS_SIGN_URL = f"{MAIN_URL}/forum/bbs/signIn"
GAME_SIGN_URL = f"{MAIN_URL}/activity/signCalendar"
HAVE_SIGN_IN_URL = f"{MAIN_URL}/activity/haveSignIn"
SIGN_CALENDAR_URL = f"{MAIN_URL}/activity/signCalendar"
SHORT_NOTE_URL = f"{MAIN_URL}/game/shortNoteInfo"
SHORT_NOTE_INFO_URL = f"{MAIN_URL}/game/shortNoteInfo"
ITEM_WEEKLY_REPORT_URL = f"{MAIN_URL}/game/itemWeeklyReport"

# post / ann
ANN_LIST_URL = f"{MAIN_URL}/forum/post/list"
GET_POST_LIST_URL = f"{MAIN_URL}/forum/post/list"
POST_LIST_URL = f"{MAIN_URL}/forum/post/list"
GET_POST_DETAIL_URL = f"{MAIN_URL}/forum/post/getPostDetail"
POST_DETAIL_URL = f"{MAIN_URL}/forum/post/getPostDetail"
LIKE_POST_URL = f"{MAIN_URL}/forum/post/postLike"
POST_LIKE_URL = f"{MAIN_URL}/forum/post/postLike"
REPLY_POST_URL = f"{MAIN_URL}/forum/post/postReply"
POST_REPLY_URL = f"{MAIN_URL}/forum/post/postReply"
SHARE_POST_URL = f"{MAIN_URL}/forum/post/postShare"

# mh
MH_LIST_URL = f"{MAIN_URL}/secret/getSecretList"

# calendar
CALENDAR_LIST_URL = f"{MAIN_URL}/forum/wiki/home/page/list"
ACTIVITY_LIST_URL = f"{MAIN_URL}/encourage/calendar/Activity/list"

# wiki
WIKI_HOME_LIST_URL = f"{MAIN_URL}/forum/wiki/home/page/list"
WIKI_LIST_URL = f"{MAIN_URL}/forum/wiki/list"
WIKI_DETAIL_URL = f"{MAIN_URL}/forum/wiki/getDetail"


def get_local_proxy_url():
    try:
        local_proxy = DNAConfig.get_config("LocalProxyUrl").data
    except KeyError:
        local_proxy = None
    return local_proxy or None


def get_need_proxy_func():
    try:
        need_proxy = DNAConfig.get_config("NeedProxyFunc").data
    except KeyError:
        need_proxy = []
    return need_proxy or []


def get_no_need_proxy_func():
    try:
        no_need = DNAConfig.get_config("NoNeedProxyFunc").data
    except KeyError:
        no_need = []
    return no_need or []
