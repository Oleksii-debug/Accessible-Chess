(() => {
  const status = document.getElementById('status');
  const requestOutput = document.getElementById('request-output');
  const leaseInput = document.getElementById('lease-input');

  const announce = (text) => { status.textContent = text; };

  const api = async () => {
    if (!window.pywebview || !window.pywebview.api) {
      throw new Error('Захисний інтерфейс недоступний.');
    }
    return window.pywebview.api;
  };

  window.addEventListener('pywebviewready', async () => {
    try {
      const bridge = await api();
      const value = await bridge.status();
      announce('Стан: заблоковано. Причина: ' + value.reason);
      document.getElementById('make-request').focus();
    } catch (error) {
      announce(String(error));
    }
  });

  document.getElementById('make-request').addEventListener('click', async () => {
    try {
      const bridge = await api();
      const value = await bridge.create_activation_request();
      if (!value.ok) {
        announce('Не вдалося створити запит: ' + value.error);
        return;
      }
      requestOutput.value = JSON.stringify(value.request, null, 2);
      requestOutput.focus();
      requestOutput.select();
      announce('Запит на активацію створено. Скопіюйте текст із поля.');
    } catch (error) {
      announce(String(error));
    }
  });

  document.getElementById('import-lease').addEventListener('click', async () => {
    try {
      const bridge = await api();
      const value = await bridge.import_entitlement(leaseInput.value);
      announce(value.ok ? 'Дозвіл імпортовано. Натисніть «Перевірити доступ знову».'
                        : 'Дозвіл відхилено: ' + value.error);
    } catch (error) {
      announce(String(error));
    }
  });

  document.getElementById('retry').addEventListener('click', async () => {
    try {
      const bridge = await api();
      const value = await bridge.retry();
      if (value.authorized) {
        announce('Доступ підтверджено. Відкриваю Accessible Chess.');
      } else {
        announce(value.error ? 'Перевірка не вдалася: ' + value.error
                             : 'Доступ і далі заблокований. Причина: ' + value.reason);
      }
    } catch (error) {
      announce(String(error));
    }
  });

  document.getElementById('close').addEventListener('click', async () => {
    const bridge = await api();
    await bridge.close();
  });
})();
