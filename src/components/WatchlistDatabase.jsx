import React, { useState } from 'react';
import { 
  Database, 
  Search, 
  Plus, 
  AlertTriangle, 
  ShieldAlert, 
  CheckCircle2, 
  Globe, 
  Filter, 
  UserX,
  FileX
} from 'lucide-react';
import { MOCK_INTERPOL_WATCHLIST } from '../data/sampleDocuments';
import { sounds } from '../utils/audio';

export function WatchlistDatabase({ soundEnabled }) {
  const [watchlist, setWatchlist] = useState(MOCK_INTERPOL_WATCHLIST);
  const [searchTerm, setSearchTerm] = useState('');
  const [showAddModal, setShowAddModal] = useState(false);
  const [newPassportNo, setNewPassportNo] = useState('');
  const [newName, setNewName] = useState('');
  const [newReason, setNewReason] = useState('');

  const filtered = watchlist.filter(item => 
    item.passportNo.toLowerCase().includes(searchTerm.toLowerCase()) ||
    item.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    item.reason.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handleAddWatchlist = (e) => {
    e.preventDefault();
    if (!newPassportNo || !newName) return;

    const newItem = {
      passportNo: newPassportNo.toUpperCase(),
      name: newName.toUpperCase(),
      reason: newReason || "Manually Flagged by Border Security Officer",
      category: "MANUALLY BLACKLISTED"
    };

    setWatchlist([newItem, ...watchlist]);
    setNewPassportNo('');
    setNewName('');
    setNewReason('');
    setShowAddModal(false);
    if (soundEnabled) sounds.playSuccess();
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="glass-panel p-4 rounded-2xl border border-slate-800 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center space-x-2">
            <Database className="w-5 h-5 text-cyan-400" />
            <h2 className="text-base font-bold text-white font-heading">
              Interpol SLTD & Ministry of Home Affairs Watchlist Intelligence
            </h2>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Cross-references document numbers against global databases for stolen passports, wanted fugitives & identity theft rings.
          </p>
        </div>

        <button
          onClick={() => setShowAddModal(true)}
          className="flex items-center space-x-2 px-3.5 py-2 bg-rose-600 hover:bg-rose-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-rose-600/30 transition"
        >
          <Plus className="w-4 h-4" />
          <span>Add Passport to Watchlist</span>
        </button>
      </div>

      {/* Search Bar */}
      <div className="glass-panel p-4 rounded-2xl border border-slate-800 space-y-4">
        <div className="relative">
          <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-3" />
          <input
            type="text"
            placeholder="Search Interpol database by Passport No, Name, or Alert Reason..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-10 pr-4 py-2.5 text-xs text-slate-100 focus:outline-none focus:border-cyan-500"
          />
        </div>

        {/* Database Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="bg-slate-950 text-slate-400 font-mono text-[11px] uppercase border-b border-slate-800">
              <tr>
                <th className="p-3">Passport / Travel Doc No</th>
                <th className="p-3">Flagged Identity Name</th>
                <th className="p-3">Alert Reason & Crime Category</th>
                <th className="p-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-medium">
              {filtered.map((item, idx) => (
                <tr key={idx} className="hover:bg-slate-900/50 transition">
                  <td className="p-3 font-mono font-bold text-cyan-400">{item.passportNo}</td>
                  <td className="p-3 font-bold text-slate-100">{item.name}</td>
                  <td className="p-3 text-slate-300">{item.reason}</td>
                  <td className="p-3">
                    <span className="px-2 py-0.5 text-[10px] font-bold bg-rose-950 text-rose-400 border border-rose-800 rounded flex items-center space-x-1 w-max">
                      <ShieldAlert className="w-3 h-3 text-rose-400" />
                      <span>{item.category}</span>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add Modal */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm">
          <div className="glass-panel p-6 rounded-2xl border border-slate-800 w-full max-w-md space-y-4">
            <h3 className="text-base font-bold text-white font-heading">Add New Passport to Watchlist</h3>
            <form onSubmit={handleAddWatchlist} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-400 mb-1 font-semibold">Passport Number *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. R5019284"
                  value={newPassportNo}
                  onChange={(e) => setNewPassportNo(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:outline-none focus:border-cyan-500 font-mono"
                />
              </div>

              <div>
                <label className="block text-slate-400 mb-1 font-semibold">Full Name *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. JOHN DOE"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div>
                <label className="block text-slate-400 mb-1 font-semibold">Reason for Blacklisting</label>
                <textarea
                  rows="3"
                  placeholder="Describe security concern, Interpol bulletin ID, or crime category..."
                  value={newReason}
                  onChange={(e) => setNewReason(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-slate-100 focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div className="flex items-center justify-end space-x-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 bg-slate-900 text-slate-300 rounded-xl hover:bg-slate-800 transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-rose-600 text-white rounded-xl font-bold shadow-md shadow-rose-600/30 hover:bg-rose-500 transition"
                >
                  Save to Database
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
