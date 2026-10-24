import { createContext } from 'react'

// What a stock's detail needs to open another stock (#114: clicking a node in Connections): your
// holdings, openStock(stock), which shows a holding on Positions and any other stock on Markets, and
// openConnections(stock), which opens the full Connections page for it (#279).
// App.jsx provides it.
export const StockNavContext = createContext({ holdings: [], openStock: null, openConnections: null })
