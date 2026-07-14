def valid_id_or_none(id_number):
    """
    Helper function to check that an id number from an indexer is valid
    Checks if we have an id_number and it is not 0 or "0"
    :param id_number: The id number to check
    :return: The id number if valid, else None
    """
    return id_number if id_number and id_number != "0" else None


def simkl_auth_guard(func):
    """Ensure method runs only when Simkl OAuth token is present."""
    import xbmcgui
    from functools import wraps

    from resources.lib.modules.globals import g
    from resources.lib.modules.global_lock import GlobalLock

    @wraps(func)
    def wrapper(*args, **kwargs):
        if g.get_setting("simkl.auth"):
            return func(*args, **kwargs)
        with GlobalLock("simkl.auth_guard"):
            if not g.get_setting("simkl.auth"):
                if xbmcgui.Dialog().yesno(g.ADDON_NAME, g.get_language_string(30471)):
                    from resources.lib.indexers.simkl import SimklAPI

                    SimklAPI().auth()
                else:
                    g.cancel_directory()
        if g.get_setting("simkl.auth"):
            return func(*args, **kwargs)
        g.cancel_directory()

    return wrapper
