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
    const toastPlaceHolderId = `${table_id}-toast`;
    const _createTableWithEvents = (response) => {
        console.log(response);
        const columns = response.content.columns;
        if (response.status == "ok" && columns !== undefined) {
            console.log("columns", columns);
            table = _createTable(table_id, url, columns);
            // Events
            table.on("cellEdited", (cell) => editCell(cell, url, toastPlaceHolderId));
            // Add/Remove buttons events
            const addButton = document.getElementById(`${table_id}-add`);
            addButton.addEventListener("click", (event) => {
                event.preventDefault();
                addTableRow(addButton, toastPlaceHolderId, table, `${url}`, columns);
            });
            const removeButton = document.getElementById(`${table_id}-remove`);
            removeButton.addEventListener("click", (event) => {
                event.preventDefault();
                removeTableRow(removeButton, toastPlaceHolderId, table, `${url}`);
            });
        } else {
            createAlertError(toastPlaceHolderId, "Failed to fetch the columns of the table");
        }
    };
    fetchWithAlert(`${url}columns`, {}, toastPlaceHolderId, _createTableWithEvents);
};

const addTableRow = (button, toastPlaceHolderId, table, url, columns) => {
    const csrftoken = document.querySelector('[name=csrfmiddlewaretoken]').value;
    _displaySpinner(button, true);
    const body = {
        method: "POST",
        headers: { "X-CSRFToken": csrftoken },
        mode: "same-origin",
    };
    fetchWithAlert(url, body, toastPlaceHolderId, (row) => {
        table.addRow(_buildRowData(row.content, columns), false, row.content.current_row);
    })
        .finally(() => {
            _displaySpinner(button, false);
        });
};

const removeTableRow = (button, toastPlaceHolderId, table, baseUrl) => {
    const lastSelectedRow = getLastSelectedRow(table);
    console.log("lastSelectedRow", lastSelectedRow);
    if (lastSelectedRow !== undefined) {
        _displaySpinner(button, true);
        const url = `${baseUrl}${lastSelectedRow.getPosition() - 1}`;
        const csrftoken = document.querySelector('[name=csrfmiddlewaretoken]').value;
        const body = {
            method: "DELETE",
            headers: { "X-CSRFToken": csrftoken },
            mode: "same-origin",
        };
        fetchWithAlert(url, body, toastPlaceHolderId, (row) => {
            lastSelectedRow.delete();
        })
            .finally(() => {
                _displaySpinner(button, false);
            });
    } else {
        createAlertWarning(toastPlaceHolderId, "No row have been selected");
    }
};

const editCell = (cell, baseUrl, toastPlaceHolderId) => {
    const csrftoken = document.querySelector('[name=csrfmiddlewaretoken]').value;
    const row = cell.getRow().getPosition() - 1;
    const url = `${baseUrl}${row}`;
    let data = {};
    data[cell.getColumn().getField()] = cell.getValue();
    const body = {
        method: "PUT",
        headers: { "X-CSRFToken": csrftoken },
        mode: "same-origin",
        body: JSON.stringify(data)
    }
    fetchWithAlert(url, body, toastPlaceHolderId, (response) => {
        if (response === undefined || response.status !== "ok") {
            cell.restoreOldValue();
            let message = response.message;
            if (message === undefined) {
                message = "Unexpectedly failed to edit the cell";
            }
            createAlertError(toastPlaceHolderId, message);
        }
    }).catch((error) => {
        cell.restoreOldValue();
        createAlertError(toastPlaceHolderId, "Unexpectedly failed to edit the cell");
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