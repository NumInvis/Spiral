import { Routes, Route } from 'react-router-dom'
import Header from './components/Header'
import Footer from './components/Footer'
import HomePage from './pages/HomePage'
import RecommendPage from './pages/RecommendPage'
import DataPage from './pages/DataPage'
import ReportPage from './pages/ReportPage'

function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <Header />
      <main className="flex-1">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/recommend" element={<RecommendPage />} />
          <Route path="/data" element={<DataPage />} />
          <Route path="/report" element={<ReportPage />} />
        </Routes>
      </main>
      <Footer />
    </div>
  )
}

export default App
