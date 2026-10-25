// Injekt-Pro.ru Interactive Client Script
document.addEventListener('DOMContentLoaded', () => {
  // 1. Mobile Menu Toggle
  const burger = document.getElementById('burger');
  const nav = document.getElementById('nav');

  if (burger && nav) {
    burger.addEventListener('click', () => {
      burger.classList.toggle('active');
      nav.classList.toggle('active');
    });

    // Close menu when clicking nav items
    nav.querySelectorAll('.nav__link').forEach(link => {
      link.addEventListener('click', () => {
        burger.classList.remove('active');
        nav.classList.remove('active');
      });
    });
  }

  // 2. Modals Management
  const modalRequest = document.getElementById('modal-request');
  const modalPolicy = document.getElementById('modal-policy');
  const openPolicyBtn = document.getElementById('openPrivacyPolicy');

  // Trigger modal from any element with data-modal
  document.querySelectorAll('[data-modal="modal-request"]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      if (modalRequest) modalRequest.classList.add('active');
    });
  });

  // Close modals
  document.querySelectorAll('[data-close-modal]').forEach(el => {
    el.addEventListener('click', () => {
      if (modalRequest) modalRequest.classList.remove('active');
    });
  });

  if (openPolicyBtn && modalPolicy) {
    openPolicyBtn.addEventListener('click', (e) => {
      e.preventDefault();
      modalPolicy.classList.add('active');
    });
  }

  document.querySelectorAll('[data-close-policy]').forEach(el => {
    el.addEventListener('click', () => {
      if (modalPolicy) modalPolicy.classList.remove('active');
    });
  });

  // Close on Escape key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (modalRequest) modalRequest.classList.remove('active');
      if (modalPolicy) modalPolicy.classList.remove('active');
    }
  });

  // 3. Phone Input Masking Helper
  const phoneInputs = document.querySelectorAll('input[type="tel"]');
  phoneInputs.forEach(input => {
    input.addEventListener('input', (e) => {
      let val = input.value.replace(/\D/g, '');
      if (!val) {
        input.value = '';
        return;
      }
      if (val[0] === '7' || val[0] === '8') val = val.substring(1);

      let formatted = '+7 (';
      if (val.length > 0) formatted += val.substring(0, 3);
      if (val.length >= 3) formatted += ') ' + val.substring(3, 6);
      if (val.length >= 6) formatted += '-' + val.substring(6, 8);
      if (val.length >= 8) formatted += '-' + val.substring(8, 10);

      input.value = formatted;
    });
  });

  // 4. File Dropzone Handling
  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('userPhoto');
  const fileList = document.getElementById('fileList');

  if (dropzone && fileInput && fileList) {
    fileInput.addEventListener('change', () => {
      fileList.innerHTML = '';
      Array.from(fileInput.files).forEach(file => {
        const tag = document.createElement('div');
        tag.className = 'file-tag';
        tag.textContent = `${file.name} (${(file.size / 1024).toFixed(0)} KB)`;
        fileList.appendChild(tag);
      });
    });

    ['dragenter', 'dragover'].forEach(eventName => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
      });
    });

    ['dragleave', 'drop'].forEach(eventName => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
      });
    });
  }

  // 5. Lead Form Submission Handler (Main form & Modal)
  function handleFormSubmit(formElement, successMsgId) {
    if (!formElement) return;

    formElement.addEventListener('submit', async (e) => {
      e.preventDefault();

      const name = formElement.querySelector('[name="name"]');
      const phone = formElement.querySelector('[name="phone"]');

      if (!name || !name.value.trim() || !phone || !phone.value.trim()) {
        alert('Пожалуйста, укажите имя и номер телефона');
        return;
      }

      const formData = {
        name: name.value.trim(),
        phone: phone.value.trim(),
        organization: formElement.querySelector('[name="organization"]')?.value.trim() || '',
        address: formElement.querySelector('[name="address"]')?.value.trim() || '',
        problem: formElement.querySelector('[name="problem"]')?.value.trim() || '',
        submittedAt: new Date().toISOString()
      };

      // Store in LocalStorage
      try {
        const existing = JSON.parse(localStorage.getItem('injekt_pro_leads') || '[]');
        existing.push(formData);
        localStorage.setItem('injekt_pro_leads', JSON.stringify(existing));
      } catch (err) {
        console.warn('LocalStorage error:', err);
      }

      // Try sending to local backend endpoint if available
      try {
        await fetch('/api/lead', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(formData)
        });
      } catch (err) {
        // Fallback gracefully for static server
      }

      // Show success message
      const successBox = document.getElementById(successMsgId);
      if (successBox) {
        successBox.classList.add('active');
      }

      // Disable submit button
      const submitBtn = formElement.querySelector('button[type="submit"]');
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.style.opacity = '0.7';
      }

      // Reset fields after delay
      setTimeout(() => {
        formElement.reset();
        if (fileList) fileList.innerHTML = '';
      }, 3000);
    });
  }

  handleFormSubmit(document.getElementById('leadForm'), 'formSuccessMessage');
  handleFormSubmit(document.getElementById('modalForm'), 'modalSuccessMessage');
});
