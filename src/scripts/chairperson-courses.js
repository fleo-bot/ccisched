'use strict';

// ── Topbar date ──
const topbarDate = document.getElementById('topbarDate');
if (topbarDate) {
  const now      = new Date();
  const dayName  = now.toLocaleDateString('en-US', { weekday: 'long' });
  const datePart = now.toLocaleDateString('en-US', { day: 'numeric', month: 'long', year: 'numeric' });
  topbarDate.textContent = `${dayName}, ${datePart}`;
}

// ── Notification bell ──
document.getElementById('notifBtn')?.addEventListener('click', () => {
  window.location.href = 'notifications.html';
});

// ── Manage button → navigate to manage page ──
document.getElementById('manageBtn')?.addEventListener('click', () => {
  window.location.href = 'manage-courses.html';
});

// ─────────────────────────────────────────────
//  DATA
// ─────────────────────────────────────────────

// ─────────────────────────────────────────────
//  DATA — loaded from the real backend
// ─────────────────────────────────────────────
let COURSES = [];

async function loadCourses() {
  try {
    const data = await API.getCourses();
    COURSES = data.map(c => ({
      code:           c.code,
      title:          c.title,
      classification: c.classification || 'IT COMMON & PROFESSIONAL COURSE',
    }));
    renderTable(activeFilter, searchQuery);
    animateCount('statCourses', COURSES.length);
  } catch (err) {
    console.error('[Courses] Failed to load:', err);
  }
}

// Section assignment coverage per course (name + pct)
const COVERAGE = [
  { name: 'Capstone Project 1',        pct: 5  },
  { name: 'Application Development',   pct: 4  },
  { name: 'Data Mining',               pct: 9  },
  { name: 'Programming 1',             pct: 9  },
  { name: 'Discrete Mathematics',      pct: 5  },
  { name: 'Database Administration',   pct: 7  },
  { name: 'Data Science',              pct: 9  },
  { name: 'Data Communication',        pct: 9  },
  { name: 'Web Development',           pct: 8  },
  { name: 'Multimedia',                pct: 7  },
  { name: 'Network Administration',    pct: 6  },
  { name: 'Mobile Application Dev',    pct: 4  },
];

const OVERALL_PCT = 82;

// ─────────────────────────────────────────────
//  BUILD COURSES TABLE
// ─────────────────────────────────────────────
const tbody = document.getElementById('crsTableBody');

function badgeClass(classification) {
  return classification.includes('ELECTIVE') ? 'crs-badge--elective' : 'crs-badge--common';
}

function renderTable(filter = 'all', query = '') {
  if (!tbody) return;
  tbody.innerHTML = '';

  COURSES.forEach(course => {
    const matchFilter = filter === 'all' || course.classification === filter;
    const matchQuery  = query === '' ||
      course.code.toLowerCase().includes(query) ||
      course.title.toLowerCase().includes(query) ||
      course.classification.toLowerCase().includes(query);

    if (!matchFilter || !matchQuery) return;

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${course.code}</td>
      <td>${course.title}</td>
      <td><span class="crs-badge ${badgeClass(course.classification)}">${course.classification}</span></td>
    `;
    tbody.appendChild(tr);
  });
}

renderTable();
loadCourses();

// ─────────────────────────────────────────────
//  FILTER PILLS
// ─────────────────────────────────────────────
let activeFilter = 'all';
let searchQuery  = '';

document.querySelectorAll('.crs-filter-pill').forEach(pill => {
  pill.addEventListener('click', () => {
    document.querySelectorAll('.crs-filter-pill').forEach(p => p.classList.remove('crs-filter-pill--active'));
    pill.classList.add('crs-filter-pill--active');
    activeFilter = pill.dataset.filter;
    renderTable(activeFilter, searchQuery);
  });
});

// ─────────────────────────────────────────────
//  INLINE TABLE SEARCH
// ─────────────────────────────────────────────
document.getElementById('crsSearch')?.addEventListener('input', function () {
  searchQuery = this.value.trim().toLowerCase();
  renderTable(activeFilter, searchQuery);
});

// ─────────────────────────────────────────────
//  COVERAGE BARS
// ─────────────────────────────────────────────
const coverageList  = document.getElementById('coverageList');
const overallBadge  = document.getElementById('overallBadge');

if (overallBadge) overallBadge.textContent = `${OVERALL_PCT}% Overall`;

if (coverageList) {
  COVERAGE.forEach(item => {
    const row = document.createElement('div');
    row.className = 'crs-cov-row';
    row.innerHTML = `
      <span class="crs-cov-name" title="${item.name}">${item.name}</span>
      <div class="crs-cov-track">
        <div class="crs-cov-fill" data-pct="${item.pct}"></div>
      </div>
      <span class="crs-cov-pct">${item.pct}/9</span>
    `;
    coverageList.appendChild(row);
  });

  // Animate bars in after paint
  requestAnimationFrame(() => {
    setTimeout(() => {
      coverageList.querySelectorAll('.crs-cov-fill').forEach(fill => {
        const pct = parseInt(fill.dataset.pct, 10);
        fill.style.width = ((pct / 9) * 100).toFixed(1) + '%';
      });
    }, 120);
  });
}

// ─────────────────────────────────────────────
//  SUMMARY STAT COUNTER ANIMATION
// ─────────────────────────────────────────────
function animateCount(id, target, duration = 800) {
  const el = document.getElementById(id);
  if (!el) return;
  const start = performance.now();
  function step(now) {
    const progress = Math.min((now - start) / duration, 1);
    el.textContent = Math.round(progress * target);
    if (progress < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

setTimeout(() => {
  animateCount('statSections', 78);
  animateCount('statAssigned', 31);
}, 100);
