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
GET_TASK_PROCESS_URL = f"{MAIN_URL}/encourage/level/getTaskProcess"
TASK_PROCESS_URL = f"{MAIN_URL}/encourage/level/getTaskProcess"
DO_TASK_URL = f"{MAIN_URL}/task/doTask"
GET_REWARD_URL = f"{MAIN_URL}/task/getReward"
BBS_SIGN_URL = f"{MAIN_URL}/user/signIn"
GAME_SIGN_URL = f"{MAIN_URL}/encourage/signin/signin"
HAVE_SIGN_IN_URL = f"{MAIN_URL}/user/haveSignInNew"
SIGN_CALENDAR_URL = f"{MAIN_URL}/encourage/signin/show"
SHORT_NOTE_URL = f"{MAIN_URL}/role/getShortNoteInfo"
SHORT_NOTE_INFO_URL = f"{MAIN_URL}/role/getShortNoteInfo"
ITEM_WEEKLY_REPORT_URL = f"{MAIN_URL}/role/getItemWeeklyReport"

# post / ann
ANN_LIST_URL = f"{MAIN_URL}/user/mine"
GET_POST_LIST_URL = f"{MAIN_URL}/forum/list"
POST_LIST_URL = f"{MAIN_URL}/forum/list"
GET_POST_DETAIL_URL = f"{MAIN_URL}/forum/getPostDetail"
POST_DETAIL_URL = f"{MAIN_URL}/forum/getPostDetail"
LIKE_POST_URL = f"{MAIN_URL}/forum/like"
POST_LIKE_URL = f"{MAIN_URL}/forum/like"
REPLY_POST_URL = f"{MAIN_URL}/forum/comment/createComment"
POST_REPLY_URL = f"{MAIN_URL}/forum/comment/createComment"
SHARE_POST_URL = f"{MAIN_URL}/encourage/level/shareTask"

# mh
MH_LIST_URL = f"{MAIN_URL}/secret/getSecretList"

# calendar
CALENDAR_LIST_URL = f"{MAIN_URL}/forum/wiki/home/page/list"
ACTIVITY_LIST_URL = f"{MAIN_URL}/encourage/calendar/Activity/list"

# wiki
WIKI_HOME_LIST_URL = f"{MAIN_URL}/forum/wiki/home/page/list"
WIKI_LIST_URL = f"{MAIN_URL}/forum/wiki/list"
WIKI_DETAIL_URL = f"{MAIN_URL}/forum/wiki/getDetail"
