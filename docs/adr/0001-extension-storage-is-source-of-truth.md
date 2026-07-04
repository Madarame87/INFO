# Extension storage is the source of truth

We store the article queue and processing state in extension-owned synchronized storage, not in Chrome bookmark folders. Chrome bookmarks are useful as an import source, but they are a poor state store because users can manually delete or move them, Chrome Sync can race with file edits, and bookmark UI state can diverge from the on-disk JSON while Chrome is running.

**Considered Options**

- Chrome bookmarks as the queue and state source.
- `chrome.storage.local` as a per-device queue.
- `chrome.storage.sync` as a lightweight cross-device queue.

**Consequences**

The extension can remember that an article is done even if the user later deletes it from the bookmark folder. The queue must stay lightweight enough for `chrome.storage.sync`, so it should store metadata and status, not article bodies.
