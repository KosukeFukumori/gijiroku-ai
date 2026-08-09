// アプリケーションルート: ルーティング設定
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { Layout } from './components/Layout'
import { RecordingList } from './pages/RecordingList'
import { RecordingDetail } from './pages/RecordingDetail'
import { Settings } from './pages/Settings'

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: '/', element: <RecordingList /> },
      { path: '/recordings/:id', element: <RecordingDetail /> },
      { path: '/settings', element: <Settings /> },
    ],
  },
])

export function App() {
  return <RouterProvider router={router} />
}
