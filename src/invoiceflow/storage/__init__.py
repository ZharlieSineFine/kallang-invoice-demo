"""WS6 blob storage: content-addressed bronze, doc-scoped silver, batch-scoped gold."""

from invoiceflow.storage.local import LocalBlobStore, gold_rel_path, silver_rel_path, words_rel_path

__all__ = ["LocalBlobStore", "gold_rel_path", "silver_rel_path", "words_rel_path"]
