const fetchWithAlert = async (url, body, toastPlaceHolderId, callback) => {
    if (url === undefined) {
        throw new Error("The url is mandatory");
    }
    return fetch(url, body).then(
        (response) => {
            if (response.ok) { return response.json(); }
            else { createAlertError(toastPlaceHolderId, "Request failed"); }
        }
    ).then((response) => {
        if (response !== undefined) return callback(response);
    });
};

const createAlertWarning = (toastPlaceHolderId, message) => {
    _createAlert(toastPlaceHolderId, message, "warning");
};

const createAlertError = (toastPlaceHolderId, message) => {
    _createAlert(toastPlaceHolderId, message, "error");
};


const _createAlert = (toastPlaceHolderId, message, alertType) => {
    const toastPlaceHolder = document.getElementById(toastPlaceHolderId);
    const toastId = `toast-${toastPlaceHolder.children.length}`;
    const toast = document.createElement("div");
    toast.innerHTML = `
    <div id=${toastId} role="alert" class="alert alert-${alertType} alert-soft">
        <span>${message}</span>
    </div>`;
    toastPlaceHolder.append(toast);
    setTimeout(() => {
        document.getElementById(toastId).remove();
    }, 4000);
};
