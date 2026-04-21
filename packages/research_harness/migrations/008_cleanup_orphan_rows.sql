-- Remove orphan rows left by deletes that bypassed foreign-key enforcement
-- (e.g. direct sqlite3 CLI usage, or connections made before PRAGMA foreign_keys=ON
-- was standard).  Safe to run multiple times (idempotent).

DELETE FROM paper_topics
WHERE paper_id NOT IN (SELECT id FROM papers);

DELETE FROM topic_paper_notes
WHERE paper_id NOT IN (SELECT id FROM papers);

DELETE FROM paper_annotations
WHERE paper_id NOT IN (SELECT id FROM papers);

DELETE FROM paper_artifacts
WHERE paper_id NOT IN (SELECT id FROM papers);

DELETE FROM bib_entries
WHERE paper_id NOT IN (SELECT id FROM papers);
