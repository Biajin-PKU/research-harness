-- Migration 037: Add domains table, merge project concept into topics
-- Strategy: add topic_id where missing, populate from projects join.
-- Old project_id columns stay (SQLite compat) but code stops using them.

-- 1. Domains table
CREATE TABLE IF NOT EXISTS domains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT (datetime('now'))
);

-- 2. Extend topics with domain_id and contributions (was on projects)
ALTER TABLE topics ADD COLUMN domain_id INTEGER REFERENCES domains(id) ON DELETE SET NULL;
ALTER TABLE topics ADD COLUMN contributions TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_topics_domain ON topics(domain_id);

-- 3. Migrate contributions from projects to topics (for existing data)
UPDATE topics SET contributions = COALESCE(
    (SELECT p.contributions FROM projects p WHERE p.topic_id = topics.id LIMIT 1),
    ''
) WHERE EXISTS (SELECT 1 FROM projects p WHERE p.topic_id = topics.id AND p.contributions != '');

-- 4. Add topic_id to tables that only had project_id
--    reviews
ALTER TABLE reviews ADD COLUMN topic_id INTEGER REFERENCES topics(id) ON DELETE CASCADE;
UPDATE reviews SET topic_id = (SELECT p.topic_id FROM projects p WHERE p.id = reviews.project_id);
CREATE INDEX IF NOT EXISTS idx_reviews_topic ON reviews(topic_id);

--    review_responses
ALTER TABLE review_responses ADD COLUMN topic_id INTEGER REFERENCES topics(id) ON DELETE CASCADE;
UPDATE review_responses SET topic_id = (
    SELECT p.topic_id FROM projects p
    JOIN review_issues ri ON ri.project_id = p.id
    WHERE ri.id = review_responses.issue_id
    LIMIT 1
);
CREATE INDEX IF NOT EXISTS idx_review_responses_topic ON review_responses(topic_id);

--    experiment_runs
ALTER TABLE experiment_runs ADD COLUMN topic_id INTEGER REFERENCES topics(id) ON DELETE CASCADE;
UPDATE experiment_runs SET topic_id = (SELECT p.topic_id FROM projects p WHERE p.id = experiment_runs.project_id);
CREATE INDEX IF NOT EXISTS idx_experiment_runs_topic ON experiment_runs(topic_id);

--    verified_numbers
ALTER TABLE verified_numbers ADD COLUMN topic_id INTEGER REFERENCES topics(id) ON DELETE CASCADE;
UPDATE verified_numbers SET topic_id = (SELECT p.topic_id FROM projects p WHERE p.id = verified_numbers.project_id);
CREATE INDEX IF NOT EXISTS idx_verified_numbers_topic ON verified_numbers(topic_id);

--    citation_verifications
ALTER TABLE citation_verifications ADD COLUMN topic_id INTEGER REFERENCES topics(id) ON DELETE CASCADE;
UPDATE citation_verifications SET topic_id = (SELECT p.topic_id FROM projects p WHERE p.id = citation_verifications.project_id);
CREATE INDEX IF NOT EXISTS idx_citation_verifications_topic ON citation_verifications(topic_id);

-- 5. Add source_topic_id to lessons
ALTER TABLE lessons ADD COLUMN source_topic_id INTEGER REFERENCES topics(id);
UPDATE lessons SET source_topic_id = (
    SELECT p.topic_id FROM projects p WHERE p.id = lessons.source_project_id
);

-- 6. Unique constraint: one orchestrator run per topic
CREATE UNIQUE INDEX IF NOT EXISTS idx_orchestrator_runs_topic_unique ON orchestrator_runs(topic_id);
