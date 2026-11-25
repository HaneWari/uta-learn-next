-- One row per install per day; the primary key makes a retried heartbeat free.
CREATE TABLE IF NOT EXISTS pings (
  iid TEXT NOT NULL,
  day TEXT NOT NULL,
  v   TEXT NOT NULL,
  os  TEXT NOT NULL,
  PRIMARY KEY (iid, day)
);

CREATE INDEX IF NOT EXISTS idx_pings_day ON pings (day);
CREATE INDEX IF NOT EXISTS idx_pings_v   ON pings (v);
