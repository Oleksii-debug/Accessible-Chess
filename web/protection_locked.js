(() => {
  const status = document.getElementById('status');
  const requestOutput = document.getElementById('request-output');
  const leaseInput = document.getElementById('lease-input');
  const onlineLogin = document.getElementById('online-login');
  const onlineRegister = document.getElementById('online-register');
  const onlineCheck = document.getElementById('online-check');
  const securityNoticeSummary = document.getElementById('security-notice-summary');
  const securityConsentAccept = document.getElementById('security-consent-accept');
  const securityConsentDecline = document.getElementById('security-consent-decline');

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
      if (value.online_available) {
        onlineLogin.disabled = false;
        onlineRegister.disabled = false;
        onlineCheck.disabled = false;
        try {
          const notice = await bridge.security_notice();
          if (notice.ok) {
            securityNoticeSummary.textContent = notice.summary;
            securityConsentAccept.disabled = false;
            securityConsentDecline.disabled = false;
          }
        } catch (_error) {
          securityConsentAccept.disabled = true;
          securityConsentDecline.disabled = true;
        }
        onlineLogin.focus();
      } else {
        onlineLogin.disabled = true;
        onlineRegister.disabled = true;
        onlineCheck.disabled = true;
        securityConsentAccept.disabled = true;
        securityConsentDecline.disabled = true;
        document.getElementById('make-request').focus();
      }
    } catch (error) {
      announce(String(error));
    }
  });

  const setSecurityConsent = async (granted) => {
    try {
      const bridge = await api();
      const value = await bridge.set_security_consent(granted);
      if (!value.ok) {
        announce('Не вдалося змінити згоду: ' + value.error);
        return;
      }
      securityNoticeSummary.textContent = value.summary;
      announce(granted
        ? 'Згоду на діагностику безпеки збережено.'
        : 'Згоду на діагностику безпеки відкликано.');
    } catch (error) {
      announce(String(error));
    }
  };

  securityConsentAccept.addEventListener('click', () => setSecurityConsent(true));
  securityConsentDecline.addEventListener('click', () => setSecurityConsent(false));

  const beginOnline = async (kind) => {
    try {
      const bridge = await api();
      const value = kind === 'login'
        ? await bridge.begin_online_login()
        : await bridge.begin_online_registration();
      if (!value.ok) {
        announce('Онлайн-доступ не вдалося розпочати: ' + value.error);
        return;
      }
      const label = kind === 'login' ? 'Вхід' : 'Реєстрацію';
      announce(label + ' відкрито у системному браузері. Після завершення поверніться сюди й натисніть «Перевірити завершення входу».');
      onlineCheck.focus();
    } catch (error) {
      announce(String(error));
    }
  };

  onlineLogin.addEventListener('click', () => beginOnline('login'));
  onlineRegister.addEventListener('click', () => beginOnline('register'));

  onlineCheck.addEventListener('click', async () => {
    try {
      const bridge = await api();
      const value = await bridge.poll_online_access();
      if (!value.ok) {
        announce('Не вдалося перевірити онлайн-доступ: ' + value.error);
        return;
      }
      if (value.authorized) {
        announce('Онлайн-доступ підтверджено. Відкриваю Accessible Chess.');
        return;
      }
      if (value.state === 'pending') {
        announce('Вхід ще не завершено у системному браузері.');
      } else {
        announce('Онлайн-доступ не підтверджено. Причина: ' + value.reason);
      }
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
