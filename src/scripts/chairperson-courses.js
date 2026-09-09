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

// Section assignment coverage per course — loaded live in loadCoverage()

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
//  COVERAGE BARS — loaded from the real backend
// ─────────────────────────────────────────────
const coverageList  = document.getElementById('coverageList');
const overallBadge  = document.getElementById('overallBadge');

async function loadCoverage() {
  try {
    const data = await API.getCoverage();
    const { total_sections, sections_covered } = data.totals;
    const overallPct = total_sections > 0 ? Math.round((sections_covered / total_sections) * 100) : 0;

    if (overallBadge) overallBadge.textContent = `${overallPct}% Overall`;
    animateCount('statSections', total_sections);
    animateCount('statAssigned', sections_covered);

    if (coverageList) {
      coverageList.innerHTML = '';
      data.courses.forEach(course => {
        const row = document.createElement('div');
        row.className = 'crs-cov-row';
        row.innerHTML = `
          <span class="crs-cov-name" title="${course.name}">${course.name}</span>
          <div class="crs-cov-track">
            <div class="crs-cov-fill" data-covered="${course.coveredSections}" data-total="${course.totalSections}"></div>
          </div>
          <span class="crs-cov-pct">${course.coveredSections}/${course.totalSections}</span>
        `;
        coverageList.appendChild(row);
      });

      // Animate bars in after paint
      requestAnimationFrame(() => {
        setTimeout(() => {
          coverageList.querySelectorAll('.crs-cov-fill').forEach(fill => {
            const covered = parseInt(fill.dataset.covered, 10);
            const total   = parseInt(fill.dataset.total, 10) || 1;
            fill.style.width = ((covered / total) * 100).toFixed(1) + '%';
          });
        }, 120);
      });
    }
  } catch (err) {
    console.error('[Courses] Failed to load coverage:', err);
  }
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

loadCoverage();
