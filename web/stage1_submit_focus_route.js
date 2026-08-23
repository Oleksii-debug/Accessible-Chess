(() => {
'use strict';

const button = document.getElementById('move-submit');
const submit = window.submitMove;
if (!button || typeof submit !== 'function' || !submit.__stage1FocusPolicy) return;
if (button.dataset.stage1SubmitFocusRouteReady === 'true') return;

function routeSubmitThroughFocusPolicy(event) {
    // index.html registered the original submitMove function object before the
    // release bootstrap replaced window.submitMove with its board-focus policy.
    // Native/UIA Invoke therefore reaches that stale listener unless this
    // capture listener routes the click through the wrapped release function
    // and prevents the stale bubble listener from submitting a second time.
    event.preventDefault();
    event.stopImmediatePropagation();
    void window.submitMove();
}

button.addEventListener('click', routeSubmitThroughFocusPolicy, true);
button.dataset.stage1SubmitFocusRouteReady = 'true';
})();
