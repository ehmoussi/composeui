"""Table/Tree component.

Contains the table and the tree components and its derivatives.

    - TableView: A table which needs a class inherited of AbstractTableItems
    - SimpleTableView: A table that works with SqliteModel/SqliteData and implements directly
        an items using the name of a table defined in the sqlite database of SqliteData.
    - LinkedTableView: Two tables that works together to display complex data.
        The first table is the master table the selection of an item in the master table
        update the contents automatically of the second table called detail table.
        Each of the tables need to implement its own AbstractTableItems.
"""
