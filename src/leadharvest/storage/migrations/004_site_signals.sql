-- v4: website facts for sales flags (copyright year, analytics, booking). NULL = not checked.
ALTER TABLE leads ADD COLUMN site_signals TEXT;
