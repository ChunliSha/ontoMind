"""QA routes must inject the DB session, not the GET-session endpoint."""

from inspect import signature

from app.api.v1.routers import qa
from app.db.session import get_session as get_db


def test_message_and_chat_depend_on_db_session():
    for fn in (
        qa.post_message,
        qa.chat,
        qa.create_session,
        qa.list_sessions,
        qa.get_qa_session,
        qa.update_session,
        qa.delete_session,
    ):
        param = signature(fn).parameters["db"]
        dep = param.default
        assert getattr(dep, "dependency", None) is get_db, fn.__name__
