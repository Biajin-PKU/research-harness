-- V2 Self-Evolution Phase 4: preference learning columns on strategies.
-- Adds ELO rating and Beta-Bernoulli posterior parameters for online
-- strategy quality estimation.

ALTER TABLE strategies ADD COLUMN elo_rating REAL DEFAULT 1500.0;
ALTER TABLE strategies ADD COLUMN beta_alpha REAL DEFAULT 1.0;
ALTER TABLE strategies ADD COLUMN beta_beta REAL DEFAULT 1.0;
