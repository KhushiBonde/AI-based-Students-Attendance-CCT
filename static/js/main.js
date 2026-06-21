// AJAX Client Logic for Real-Time Polling & Manual Overrides
document.addEventListener('DOMContentLoaded', () => {
    const dashboardFeed = document.getElementById('dashboard-feed');
    if (!dashboardFeed) return; // Only execute on dashboard page

    let activeSession = null;
    let pollInterval = null;
    let timerInterval = null;

    // Elements
    const sessionDetails = document.getElementById('session-details');
    const noSessionState = document.getElementById('no-session-state');
    const subjectLabel = document.getElementById('session-subject');
    const sectionLabel = document.getElementById('session-section');
    const timerLabel = document.getElementById('session-timer');
    
    const countEnrolled = document.getElementById('count-enrolled');
    const countPresent = document.getElementById('count-present');
    const countAbsent = document.getElementById('count-absent');
    const attendanceTableBody = document.getElementById('attendance-table-body');
    const stopSessionBtn = document.getElementById('stop-session-btn');

    // Confirm session stop
    if (stopSessionBtn) {
        stopSessionBtn.addEventListener('click', (e) => {
            if (!confirm('Are you sure you want to stop this session? The attendance file will be finalized.')) {
                e.preventDefault();
            }
        });
    }

    // Start polling status
    checkSessionStatus();
    pollInterval = setInterval(checkSessionStatus, 3000);

    function checkSessionStatus() {
        fetch('/api/session/status')
            .then(res => res.json())
            .then(data => {
                if (data.active) {
                    activeSession = data;
                    showSessionUI();
                    fetchAttendanceRecords();
                } else {
                    activeSession = null;
                    showNoSessionUI();
                }
            })
            .catch(err => console.error("Error checking session status:", err));
    }

    function showSessionUI() {
        if (noSessionState) noSessionState.style.display = 'none';
        if (sessionDetails) sessionDetails.style.display = 'block';
        
        if (subjectLabel) subjectLabel.innerText = activeSession.subject;
        if (sectionLabel) sectionLabel.innerText = activeSession.section;
        
        // Start live timer if not already running
        startTimer(activeSession.start_time);
    }

    function showNoSessionUI() {
        if (sessionDetails) sessionDetails.style.display = 'none';
        if (noSessionState) noSessionState.style.display = 'block';
        if (timerInterval) {
            clearInterval(timerInterval);
            timerInterval = null;
        }
    }

    function startTimer(startTimeIso) {
        if (timerInterval) return;
        const startTime = new Date(startTimeIso).getTime();
        
        function updateTimer() {
            const now = new Date().getTime();
            const diff = now - startTime;
            
            if (diff < 0) {
                if (timerLabel) timerLabel.innerText = "00:00";
                return;
            }
            
            const minutes = Math.floor(diff / 60000);
            const seconds = Math.floor((diff % 60000) / 1000);
            
            const mm = minutes < 10 ? '0' + minutes : minutes;
            const ss = seconds < 10 ? '0' + seconds : seconds;
            
            if (timerLabel) timerLabel.innerText = `${mm}:${ss}`;
        }
        
        updateTimer();
        timerInterval = setInterval(updateTimer, 1000);
    }

    function fetchAttendanceRecords() {
        fetch('/api/attendance')
            .then(res => res.json())
            .then(data => {
                if (!data.active) return;
                
                // Update stats counts
                const presentCount = data.present_count;
                const totalEnrolled = data.total_enrolled || activeSession.total_enrolled;
                const absentCount = Math.max(0, totalEnrolled - presentCount);
                
                if (countEnrolled) countEnrolled.innerText = totalEnrolled;
                if (countPresent) countPresent.innerText = presentCount;
                if (countAbsent) countAbsent.innerText = absentCount;
                
                // Build attendance list map
                updateAttendanceTable(data.records, data.enrolled_students);
            })
            .catch(err => console.error("Error fetching attendance list:", err));
    }

    function updateAttendanceTable(presentRecords, enrolledStudents) {
        if (!attendanceTableBody) return;
        
        // Map present records by roll number
        const presentMap = {};
        presentRecords.forEach(rec => {
            presentMap[rec.roll_number] = rec;
        });

        let rowsHtml = '';
        
        if (!enrolledStudents || enrolledStudents.length === 0) {
            rowsHtml = `<tr><td colspan="5" class="empty-state">No students enrolled in this section.</td></tr>`;
            attendanceTableBody.innerHTML = rowsHtml;
            return;
        }

        enrolledStudents.forEach(student => {
            const roll = student.roll_number;
            const name = student.name;
            const isPresent = roll in presentMap;
            
            let timeStr = '-';
            let confStr = '-';
            let statusBadge = `<span class="badge badge-absent">Absent</span>`;
            let actionBtn = `<button class="btn btn-primary btn-sm mark-btn" data-roll="${roll}" data-action="present">Mark Present</button>`;
            
            if (isPresent) {
                const rec = presentMap[roll];
                const timeObj = new Date(rec.timestamp);
                timeStr = timeObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                
                // Show confidence score with %
                confStr = rec.confidence_score ? `${Math.round(rec.confidence_score * 100)}%` : '100% (Manual)';
                
                statusBadge = `<span class="badge badge-present">Present</span>`;
                actionBtn = `<button class="btn btn-secondary btn-sm mark-btn" data-roll="${roll}" data-action="absent">Mark Absent</button>`;
            }
            
            rowsHtml += `
                <tr id="row-${roll}">
                    <td><strong>${roll}</strong></td>
                    <td>${name}</td>
                    <td>${statusBadge}</td>
                    <td>${timeStr}</td>
                    <td>${confStr}</td>
                    <td>${actionBtn}</td>
                </tr>
            `;
        });
        
        attendanceTableBody.innerHTML = rowsHtml;
        
        // Bind override click handlers
        document.querySelectorAll('.mark-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const roll = this.getAttribute('data-roll');
                const action = this.getAttribute('data-action');
                triggerOverride(roll, action);
            });
        });
    }

    function triggerOverride(rollNumber, action) {
        fetch('/admin/attendance/override', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: `roll_number=${encodeURIComponent(rollNumber)}&action=${action}`
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                // Instantly fetch records to update screen
                fetchAttendanceRecords();
            } else {
                alert('Override failed: ' + data.message);
            }
        })
        .catch(err => {
            console.error('Error override request:', err);
            alert('Error updating attendance record.');
        });
    }
});
