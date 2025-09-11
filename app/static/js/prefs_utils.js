(function () {
  'use strict';

  function pad2(n) { return String(n).padStart(2, '0'); }
  function ymd(year, month, day) { return `${year}-${pad2(month)}-${pad2(day)}`; }

  async function fetchAllPreferences(year, month) {
    const res = await fetch(`/preferences/all?year=${year}&month=${month}`);
    if (!res || !res.ok) throw new Error('선호도 데이터를 불러올 수 없습니다.');
    return await res.json();
  }

  function parseShiftPreferences(prefList) {
    // Returns Map<nurse_id, { O: {day:wt|''}, D:{}, E:{}, N:{} }>
    const result = new Map();
    (prefList || []).forEach(item => {
      const nurseId = String(item.nurse_id);
      const shifts = item?.data?.shift || {};
      const normalized = {};
      ['O', 'D', 'E', 'N'].forEach(code => {
        const raw = shifts[code];
        if (!raw) return;
        if (Array.isArray(raw)) {
          // Array form: ["1","3",...]
          const obj = {};
          raw.forEach(d => { obj[String(d)] = ''; });
          normalized[code] = obj;
        } else if (typeof raw === 'object') {
          // Object form: {"12": 3.0}
          const obj = {};
          Object.keys(raw).forEach(k => { obj[String(k)] = raw[k]; });
          normalized[code] = obj;
        }
      });
      result.set(nurseId, normalized);
    });
    return result;
  }

  function buildOffDateMap(prefList, year, month) {
    // Returns Map<nurse_id, [YYYY-MM-DD,...]> from O shift only
    const offMap = new Map();
    const parsed = parseShiftPreferences(prefList);
    parsed.forEach((shiftObj, nurseId) => {
      const off = shiftObj?.O || {};
      const days = Object.keys(off);
      const dates = days.map(d => {
        // d may be 'YYYY-MM-DD' already
        if (String(d).includes('-')) return String(d);
        const dayNum = parseInt(d, 10);
        return ymd(year, month, dayNum);
      });
      offMap.set(nurseId, dates);
    });
    return offMap;
  }

  window.PrefsUtils = {
    fetchAllPreferences,
    parseShiftPreferences,
    buildOffDateMap,
  };
})(); 