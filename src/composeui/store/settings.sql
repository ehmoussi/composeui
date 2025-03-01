PRAGMA journal_mode = WAL;
-- The temporary nature of the use of the sqlite database make the fsync unecessary
-- because if the application crash and the database is corrupted it doesn't matter since
-- the file is removed anyway.
-- If a system of recovery is implemented then the value of synchronous should be 1
-- because the file need to be reopened
PRAGMA synchronous = 0;
PRAGMA foreign_keys = ON;
PRAGMA recursive_triggers = ON;
PRAGMA user_version = 1;
