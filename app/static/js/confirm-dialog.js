// Opens a <dialog data-confirm-dialog> when a matching [data-confirm] trigger
// is clicked, instead of the browser's unstyled native confirm().
document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-confirm]");
    if (!trigger) return;
    const dialog = document.getElementById(trigger.dataset.confirm);
    if (dialog) dialog.showModal();
});
