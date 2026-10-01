-- v3: website signals for agencies (V2, F17).
ALTER TABLE leads ADD COLUMN tech TEXT NOT NULL DEFAULT '[]';
ALTER TABLE leads ADD COLUMN mobile_viewport INTEGER;
