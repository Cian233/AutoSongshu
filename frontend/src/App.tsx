import { Routes, Route, Navigate } from 'react-router-dom';
import ChatPage from './pages/ChatPage';
import KnowledgeListPage from './pages/KnowledgeListPage';
import KnowledgeDetailPage from './pages/KnowledgeDetailPage';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ChatPage />} />
      <Route path="/knowledge" element={<KnowledgeListPage />} />
      <Route path="/knowledge/bases/:id/:tab" element={<KnowledgeDetailPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
