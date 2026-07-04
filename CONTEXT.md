# Article Queue Extension

This context describes a Chrome extension that turns saved article links into a durable processing queue. Chrome bookmarks may provide input, but the extension owns the processing state.

## Language

**Article**:
A URL saved by the user for later processing. An article may originate from a bookmark or from a direct save action.
_Avoid_: bookmark, page, link when referring to queued work

**Article Queue**:
The extension-owned collection of articles and their processing states.
_Avoid_: bookmark folder, reading list

**Bookmark Source**:
A Chrome bookmark folder used as an import source for articles. It is not the source of truth for processing state.
_Avoid_: queue, database, task list

**Queue Record**:
The extension-owned record for one article, including identity, source metadata, and processing state.
_Avoid_: bookmark item

**Article Key**:
The stable identity for an article across devices, derived from a normalized URL. Chrome bookmark IDs may be recorded as source metadata but are not article identity.
_Avoid_: bookmark id, tab id

**Processing State**:
The durable state for one article under one processing type. It reflects the extension's view of external processing, not the article's location in Chrome bookmarks.
_Avoid_: bookmark status

**Done Article**:
An article whose external processing flow completed successfully for a specific processing type and should not be processed again for that type.
_Avoid_: translated article, deleted article, read article

**External Processing Flow**:
A process outside the queue that performs work for an article and reports success back to the extension.
_Avoid_: translation when referring to processing in general

**Processing Type**:
A named category of external processing, such as translation, transcript extraction, or book acquisition. Each processing type has independent state for the same article, and each maps to one external processing flow. Types are registered data, not code; the first registered type is `translate`.
_Avoid_: global status, action when referring to durable processing identity

**Completion Report**:
A structured message from an external processing flow stating the outcome (done, failed, or a processing claim) for one or more articles under one processing type. Reports are the only way external flows change processing state.
_Avoid_: log, notification

**Processing Article**:
An article an external processing flow has claimed for one processing type but not yet reported on. The claim is only valid while the flow is running; if the flow stops without reporting, the claim lapses and the article returns to pending.
_Avoid_: running article, locked article

**Ignored Article**:
An article the user has explicitly excluded from a processing type. It is not offered to external flows and is not pending.
_Avoid_: deleted article, failed article

**Archived Record**:
A queue record whose processing is finished and which has been moved out of the active queue. It still counts as processing history: re-importing the same article must not make it pending again.
_Avoid_: deleted record
