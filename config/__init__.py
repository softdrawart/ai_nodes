# -*- coding: utf-8 -*-
try:
    from .config_Internal import CONFIG
except ImportError:
    CONFIG = None
from .config_proxy import init_session, get_token, is_internal, shutdown, session_run