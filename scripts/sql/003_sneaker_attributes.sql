-- Presentation attributes only; inventory/price/qualification remain server-owned.
ALTER TABLE skus ADD COLUMN size_eu VARCHAR(8) NOT NULL DEFAULT '',
 ADD COLUMN category VARCHAR(16) NOT NULL DEFAULT '',
 ADD COLUMN colorway VARCHAR(64) NOT NULL DEFAULT '';
