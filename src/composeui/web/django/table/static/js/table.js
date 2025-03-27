Tabulator.extendModule("keybindings", "actions", {
    "deselectAll": () => {
        this.table.deselectRow();
    },
});

const createTable = (table_id, url) => {
    if (url === undefined) {
        throw new Error("The url is mandatory");
    }
    console.log(`${url}/columns`);
    fetch(`${url}/columns`)
        .then((response) => { if (response.ok) return response.json() }
        ).then((response) => {
            console.log(response);
            if (response["status"] == "ok") {
                const columns = response["content"]["columns"];
                console.log(columns);
                if (columns === undefined) {
                    throw new Error("Failed to fetch the columns of the table");
                }
                console.log(table_id);
                _createTable(table_id, url, columns);
            }
        });
};

const addTableRow = (url) => {
    const csrftoken = document.querySelector('[name=csrfmiddlewaretoken]').value;
    fetch(url,
        {
            method: "POST",
            headers: { "X-CSRFToken": csrftoken },
            mode: "same-origin",
            // body: JSON.stringify({ index: lastSelectedIndex })
        }
    )
        .then((response) => response.json())
        .then((row) => {
            console.log(row);
            // table.addRow(row, false, row.index);
        });
};

const _extract_data = (url, params, columns, response) => {
    console.log(response);
    const data = response.content.map(row => {
        let rowData = {}
        columns.forEach((column_info, idx) => {
            rowData[column_info.field] = row.data[idx];
        })
        return rowData;
    });
    console.log("extracted data", data);
    return data;
};

const _createTable = (table_id, url, columns) => {
    if (Object.keys(columns).length === 0) {
        throw new Error("The table should have at least one column");
    }
    const extract_data = (url, params, response) => {
        return _extract_data(url, params, columns, response);
    }
    return new Tabulator(`#${table_id}`, {
        ajaxURL: url,
        ajaxConfig: "GET",
        ajaxResponse: extract_data,
        layout: "fitDataStretch",
        responsiveLayout: true,
        columns: columns,
        // [
        //     // { title: "Id", field: "id", width: 150 },
        //     // { title: "Index", field: "index", width: 150 },
        //     {
        //         title: "Name", field: "name", width: 150, editor: "input",
        //         // cellEdited: (cell) => { fetchEditVariableName(urlEditName, cell); }
        //     },
        //     {
        //         title: "Distribution", field: "distribution", editor: "list",
        //         // editorParams: {
        //         //     valuesURL: `${urlDistribution}`,
        //         //     placeholderLoading: "Loading Remote Data...",
        //         // },
        //         // cellEdited: (cell) => { fetchEditVariableDistribution(urlEditDistribution, cell); }
        //     },
        // ],
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