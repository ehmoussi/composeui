CREATE TRIGGER IF NOT EXISTS synchronize_line_tree_insert
    AFTER INSERT ON line
BEGIN
    INSERT INTO line_tree(l_id) VALUES(NEW.l_id);
END;

CREATE TRIGGER IF NOT EXISTS synchronize_line_tree_delete
    AFTER DELETE ON line
BEGIN
    DELETE FROM line_tree WHERE l_id=OLD.l_id;
END;
