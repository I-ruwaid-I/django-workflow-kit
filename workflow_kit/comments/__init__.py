"""Comment public API.

Re-exports the comment service so applications can ``from workflow_kit.comments
import add_comment, execution_comments``.
"""

from workflow_kit.comments.service import add_comment, execution_comments

__all__ = ["add_comment", "execution_comments"]
