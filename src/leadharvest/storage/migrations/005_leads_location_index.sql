-- v5: dedupe rule 4 (similar name within ~100 m) looks leads up by a lat/lon box.
CREATE INDEX idx_leads_lat_lon ON leads(lat, lon);
