Tabulator.extendModule("keybindings", "actions", {
    "deselectAll": () => {
        this.table.deselectRow();
    },
});


const getLastSelectedRow = (table) => {
    const selectedRows = table.getSelectedRows();
    return (
        selectedRows.length > 0 ?
            selectedRows[selectedRows.length - 1] :
            undefined
    );
}

const getLastSelectedId = () => {
    const selectedData = table.getSelectedData();
    return (
        selectedData.length > 0 ?
            selectedData[selectedData.length - 1].id :
            ""
    );
};

const createTable = (table_id, url) => {
    if (url === undefined) {
        throw new Error("The url is mandatory");
    }
    fetch(`${url}/columns`)
        .then((response) => { if (response.ok) return response.json() }
        ).then((response) => {
            console.log(response);
            if (response.status == "ok") {
                const columns = response.content.columns;
                if (columns === undefined) {
                    throw new Error("Failed to fetch the columns of the table");
                }
                console.log("columns", columns);
                table = _createTable(table_id, url, columns);
                // Events
                table.on("cellEdited", (cell) => editCell(cell, url));
                // Add/Remove buttons events
                const addButton = document.getElementById(`${table_id}-add`);
                addButton.addEventListener("click", (event) => {
                    event.preventDefault();
                    addTableRow(addButton, table, `${url}/`, columns);
                });
                const removeButton = document.getElementById(`${table_id}-remove`);
                removeButton.addEventListener("click", (event) => {
                    event.preventDefault();
                    removeTableRow(removeButton, table, `${url}`);
                });
            }
        });
};

const addTableRow = (button, table, url, columns) => {
    _displaySpinner(button, true);
    console.log(table);
    const csrftoken = document.querySelector('[name=csrfmiddlewaretoken]').value;
    fetch(url,
        {
            method: "POST",
            headers: { "X-CSRFToken": csrftoken },
            mode: "same-origin",
        }
    )
        .then((response) => response.json())
        .then((row) => {
            console.log(row.content.data);
            table.addRow(_buildRowData(row.content, columns), false, row.content.current_row);
        }).finally(() => {
            _displaySpinner(button, false);
        });
};

const removeTableRow = (button, table, url) => {
    _displaySpinner(button, true);
    const csrftoken = document.querySelector('[name=csrfmiddlewaretoken]').value;
    const lastSelectedRow = getLastSelectedRow(table);
    console.log(lastSelectedRow);
    if (lastSelectedRow !== undefined) {
        fetch(`${url}/${lastSelectedRow.getPosition() - 1}`,
            {
                method: "DELETE",
                headers: { "X-CSRFToken": csrftoken },
                mode: "same-origin",
            }
        )
            .then((response) => response.json())
            .then((row) => {
                console.log(row);
                lastSelectedRow.delete();
            }).finally(() => {
                _displaySpinner(button, false);
            });
    }
};

const editCell = (cell, url) => {
    const csrftoken = document.querySelector('[name=csrfmiddlewaretoken]').value;
    const row = cell.getRow().getPosition() - 1;
    let data = {};
    data[cell.getColumn().getField()] = cell.getValue();
    fetch(`${url}/${row}`,
        {
            method: "PUT",
            headers: { "X-CSRFToken": csrftoken },
            mode: "same-origin",
            body: JSON.stringify(data)
        }
    ).then((response) => {
        if (response.status == 200) {
            return response.json();
        } else {
            cell.restoreOldValue();
        }
    }).then((response) => {
        console.log(response);
        if (response.status !== "ok") {
            cell.restoreOldValue();
        }
    }).catch((error) => {
        cell.restoreOldValue();
    });
};

const _displaySpinner = (button, isVisible) => {
    const spanElement = button.querySelector("span");
    spanElement.hidden = !isVisible;
}


const _buildRowData = (row, columns) => {
    let rowData = {}
    columns.forEach((column_info, idx) => {
        rowData[column_info.field] = row.data[idx];
    })
    return rowData;
};

const _buildData = (url, params, columns, response) => {
    const data = response.content.map(row => _buildRowData(row, columns));
    return data;
};

const _createTable = (table_id, url, columns) => {
    if (Object.keys(columns).length === 0) {
        throw new Error("The table should have at least one column");
    }
    const extractData = (url, params, response) => {
        return _buildData(url, params, columns, response);
    }
    return new Tabulator(`#${table_id}`, {
        ajaxURL: url,
        ajaxConfig: "GET",
        ajaxResponse: extractData,
        layout: "fitDataStretch",
        responsiveLayout: true,
        columns: columns,
        // set height of table (in CSS or here), this enables the Virtual DOM and improves 
        // render speed dramatically (can be any valid css height value)
        height: "vh-100",
        minHeight: 310,
        selectableRows: 1,
        // selectableRowsRangeMode: "click",
        keybindings: {
            "deselectAll": "27", //bind deselectAll function to esc
        },
        editTriggerEvent: "dblclick", //trigger edit on double click
    });
};