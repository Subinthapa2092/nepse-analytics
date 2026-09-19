-- Floorsheet storage.
--
-- We do NOT store every raw trade in Postgres: NEPSE does ~60-110k trades a day,
-- which is ~15-25 million rows a year and will not fit a free Supabase database.
-- Broker accumulation/distribution only needs "who bought / sold how much of which
-- symbol on which day", so we store that (a few thousand rows per day) and keep
-- the raw trades as compressed files on disk (data/raw/floorsheet/, git-ignored).

create table if not exists broker_daily_summary (
    trade_date   date          not null,
    symbol       text          not null,
    broker       text          not null,      -- broker number as shown on the floorsheet
    buy_qty      bigint        not null default 0,
    buy_amount   numeric(20,2) not null default 0,
    buy_trades   integer       not null default 0,
    sell_qty     bigint        not null default 0,
    sell_amount  numeric(20,2) not null default 0,
    sell_trades  integer       not null default 0,
    primary key (trade_date, symbol, broker)
);

create index if not exists idx_broker_daily_symbol_date on broker_daily_summary (symbol, trade_date);
create index if not exists idx_broker_daily_broker_date on broker_daily_summary (broker, trade_date);

-- One row per FULLY scraped day. A day only appears here if every page was read,
-- so "not in this table" always means "needs (re)scraping".
create table if not exists floorsheet_ingest_log (
    trade_date    date          primary key,
    trade_rows    integer       not null,
    pages         integer       not null,
    total_amount  numeric(22,2),
    completed_at  timestamptz   not null default now()
);
