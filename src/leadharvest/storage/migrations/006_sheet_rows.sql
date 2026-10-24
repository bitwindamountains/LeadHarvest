-- v6: leads written to each Google Sheet tab (decision D4), so a row the client deletes is
-- not appended again on the next export.
CREATE TABLE sheet_rows (
    sheet_id    TEXT NOT NULL,
    tab         TEXT NOT NULL,
    lead_id     TEXT NOT NULL REFERENCES leads(lead_id) ON DELETE CASCADE,
    written_at  TEXT NOT NULL,
    PRIMARY KEY (sheet_id, tab, lead_id)
);
