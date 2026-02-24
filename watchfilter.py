# /// script
# requires-python = '>=3.11'
# dependencies = [
#   'watchfiles',
# ]
# ///

from watchfiles import Change, DefaultFilter


class ContentFilter(DefaultFilter):
    content_extensions = ('.rst',)

    def __call__(self, change: Change, path: str) -> bool:
        return super().__call__(change, path) and path.endswith(self.content_extensions)
