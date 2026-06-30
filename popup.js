document
    .getElementById("scanBtn")
    .addEventListener(
        "click",
        async () => {

            const status =
                document.getElementById(
                    "status"
                );

            status.innerText =
                "Starting...";

            try {

                const fromDate =
                    document.getElementById("fromDate").value || null;

                const toDate =
                    document.getElementById("toDate").value || null;

                const mode =
                    document.getElementById("mode").value;

                const expiry =
                    document.getElementById("expiry").value || null;

                const [tab] =
                    await chrome.tabs.query(
                        {
                            active: true,
                            currentWindow: true
                        }
                    );

                const response =
                    await chrome.tabs.sendMessage(
                        tab.id,
                        {
                            action: "runScan",
                            fromDate,
                            toDate,
                            mode,
                            expiry
                        }
                    );

                status.innerText =
                    response?.message ||
                    "No Response";

            } catch (e) {

                console.error(e);

                status.innerText =
                    "Open a Sensibull tab first";
            }
        }
    );
