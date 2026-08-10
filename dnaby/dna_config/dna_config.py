from .config_default import CONFIG_DEFAULT
from .config_manager import ConfigManager
from .config_sign import CONFIG_SIGN

DNAConfig = ConfigManager("DNAUID配置", CONFIG_DEFAULT)
DNASignConfig = ConfigManager("DNAUID签到配置", CONFIG_SIGN)
