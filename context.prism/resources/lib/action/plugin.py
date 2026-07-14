from abc import ABCMeta
from urllib.parse import quote
from urllib.parse import urlencode

from resources.lib.action import ContextAction
from resources.lib.action import PRISM_ADDON_ID
from resources.lib.tools import url_quoted_action_args


class ContextPluginAction(ContextAction, metaclass=ABCMeta):
    @property
    def action_type(self):
        return "RunPlugin({path})"

    def handle_args(self, *args, **kwargs):
        pass


class PlayFromRandomPoint(ContextPluginAction):
    @property
    def action(self):
        return "playFromRandomPoint"


class QuickResume(ContextPluginAction):
    @property
    def action(self):
        return "forceResumeShow"


class SimklManager(ContextPluginAction):
    @property
    def action(self):
        return "simklManager"

    def handle_path(self):
        args = {"action": self.action, "action_args": url_quoted_action_args(self.action_args)}
        self.action_path = f"plugin://{PRISM_ADDON_ID}/?{urlencode(args, quote_via=quote)}"


class ShufflePlay(ContextPluginAction):
    @property
    def action(self):
        return "shufflePlay"


class FindRecommendations(ContextPluginAction):
    @property
    def action(self):
        return "simklRecommendations"

    def handle_args(self, *args, **kwargs):
        from resources.lib.ids import normalize_action_args
        from resources.lib.tools import attach_source_catalog

        self.action_args = attach_source_catalog(normalize_action_args(self.action_args))

    def handle_path(self):
        args = {
            "action": self.action,
            "context_menu": "1",
            "action_args": url_quoted_action_args(self.action_args),
        }
        self.action_path = f"plugin://{PRISM_ADDON_ID}/?{urlencode(args, quote_via=quote)}"


class FindRelations(ContextPluginAction):
    @property
    def action(self):
        return "simklRelations"

    def handle_args(self, *args, **kwargs):
        from resources.lib.ids import normalize_action_args
        from resources.lib.tools import attach_source_catalog

        self.action_args = attach_source_catalog(normalize_action_args(self.action_args))

    def handle_path(self):
        args = {
            "action": self.action,
            "context_menu": "1",
            "action_args": url_quoted_action_args(self.action_args),
        }
        self.action_path = f"plugin://{PRISM_ADDON_ID}/?{urlencode(args, quote_via=quote)}"
