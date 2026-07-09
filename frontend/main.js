document.addEventListener('DOMContentLoaded', () => {
    const name1Input = document.getElementById('name1');
    const name2Input = document.getElementById('name2');
    const name1Error = document.getElementById('name1-error');
    const name2Error = document.getElementById('name2-error');
    const compareBtn = document.getElementById('compare-btn');
    const btnText = document.getElementById('btn-text');
    const btnSpinner = document.getElementById('btn-spinner');
    const btnArrow = document.getElementById('btn-arrow');
    const resultSection = document.getElementById('result-section');
    const scoreValue = document.getElementById('score-value');
    const scorePath = document.getElementById('score-path');
    const code1 = document.getElementById('code1');
    const code2 = document.getElementById('code2');
    const similarityStatus = document.getElementById('similarity-status');
    const chips = document.querySelectorAll('.chip');
    const toastContainer = document.getElementById('toast-container');

    let animationFrameId = null;

    // Remove error highlights on user input
    name1Input.addEventListener('input', () => {
        name1Input.classList.remove('error');
        name1Error.classList.add('hidden');
    });
    name2Input.addEventListener('input', () => {
        name2Input.classList.remove('error');
        name2Error.classList.add('hidden');
    });

    // Toast Notification helper
    function showToast(message, type = 'error') {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `
            <span class="toast-message">${message}</span>
            <button class="toast-close">&times;</button>
        `;
        toastContainer.appendChild(toast);

        // Slide/Fade in
        setTimeout(() => toast.classList.add('show'), 10);

        // Auto remove
        const autoClose = setTimeout(() => closeToast(toast), 4000);

        // Manual close
        toast.querySelector('.toast-close').addEventListener('click', () => {
            clearTimeout(autoClose);
            closeToast(toast);
        });
    }

    function closeToast(toast) {
        toast.classList.remove('show');
        toast.addEventListener('transitionend', () => {
            toast.remove();
        });
    }

    async function detectSimilarity() {
        const name1 = name1Input.value.trim();
        const name2 = name2Input.value.trim();

        // Reset error styling
        name1Input.classList.remove('error');
        name2Input.classList.remove('error');
        name1Error.classList.add('hidden');
        name2Error.classList.add('hidden');

        let hasError = false;
        if (!name1) {
            name1Input.classList.add('error');
            name1Error.textContent = 'This field is required';
            name1Error.classList.remove('hidden');
            hasError = true;
        }
        if (!name2) {
            name2Input.classList.add('error');
            name2Error.textContent = 'This field is required';
            name2Error.classList.remove('hidden');
            hasError = true;
        }

        if (hasError) {
            return;
        }

        // Toggle Loading States
        setLoading(true);

        try {
            const response = await fetch('/compare', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name1, name2, enable_aliases: true })
            });

            const data = await response.json();

            if (!response.ok) {
                // Backend validation errors (HTTP 400)
                const errMsg = data.detail || 'An error occurred during evaluation.';
                if (data.detail && data.detail.includes('First')) {
                    name1Input.classList.add('error');
                    name1Error.textContent = errMsg;
                    name1Error.classList.remove('hidden');
                } else if (data.detail && data.detail.includes('Second')) {
                    name2Input.classList.add('error');
                    name2Error.textContent = errMsg;
                    name2Error.classList.remove('hidden');
                } else {
                    name1Input.classList.add('error');
                    name2Input.classList.add('error');
                    showToast(errMsg);
                }
                throw new Error(errMsg);
            }

            updateUI(data);
        } catch (error) {
            console.error('API Error:', error);
            showToast(error.message || 'Could not connect to the backend. Make sure the FastAPI server is running.');
        } finally {
            setLoading(false);
        }
    }

    function setLoading(isLoading) {
        compareBtn.disabled = isLoading;
        name1Input.disabled = isLoading;
        name2Input.disabled = isLoading;

        if (isLoading) {
            btnText.textContent = 'Analyzing...';
            btnSpinner.classList.remove('hidden');
            btnArrow.classList.add('hidden');
        } else {
            btnText.textContent = 'Detect Similarity';
            btnSpinner.classList.add('hidden');
            btnArrow.classList.remove('hidden');
        }
    }

    function updateUI(data) {
        resultSection.classList.remove('hidden');
        
        // Reset and animate score
        let currentScore = 0;
        const targetScore = data.score;
        const duration = 800; // ms
        const startTime = performance.now();

        // Update stroke color immediately or gradually
        let strokeColor = '#ef4444';
        if (targetScore >= 90) {
            strokeColor = '#10b981'; // Green
        } else if (targetScore >= 75) {
            strokeColor = '#f59e0b'; // Amber
        }

        scorePath.style.stroke = strokeColor;

        if (animationFrameId) {
            cancelAnimationFrame(animationFrameId);
        }

        function animate(currentTime) {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / duration, 1);
            
            // Easing function (easeOutQuad)
            const easeProgress = progress * (2 - progress);
            currentScore = Math.floor(easeProgress * targetScore);
            scoreValue.textContent = currentScore;
            
            // Update circular progress SVG
            const dashArray = `${currentScore}, 100`;
            scorePath.setAttribute('stroke-dasharray', dashArray);

            if (progress < 1) {
                animationFrameId = requestAnimationFrame(animate);
            }
        }
        animationFrameId = requestAnimationFrame(animate);

        // Update phonetic codes or display warning if missing
        code1.textContent = data.code1 || 'N/A';
        code2.textContent = data.code2 || 'N/A';

        // Update status badge design based on match type and score
        if (data.score >= 90) {
            similarityStatus.textContent = data.match_type === 'alias' ? 'Verified Alias' : 'Highly Similar';
            similarityStatus.style.background = 'rgba(16, 185, 129, 0.15)';
            similarityStatus.style.color = '#10b981';
            similarityStatus.style.borderColor = 'rgba(16, 185, 129, 0.3)';
        } else if (data.score >= 75) {
            similarityStatus.textContent = 'Likely Match';
            similarityStatus.style.background = 'rgba(245, 158, 11, 0.15)';
            similarityStatus.style.color = '#f59e0b';
            similarityStatus.style.borderColor = 'rgba(245, 158, 11, 0.3)';
        } else {
            similarityStatus.textContent = 'Distinct Entities';
            similarityStatus.style.background = 'rgba(239, 68, 68, 0.15)';
            similarityStatus.style.color = '#ef4444';
            similarityStatus.style.borderColor = 'rgba(239, 68, 68, 0.3)';
        }
    }

    compareBtn.addEventListener('click', detectSimilarity);

    // Enter key submit triggers
    [name1Input, name2Input].forEach(input => {
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !compareBtn.disabled) {
                detectSimilarity();
            }
        });
    });

    // Sample chips click action
    chips.forEach(chip => {
        chip.addEventListener('click', () => {
            if (compareBtn.disabled) return;
            name1Input.value = chip.dataset.n1;
            name2Input.value = chip.dataset.n2;
            detectSimilarity();
        });
    });
});
