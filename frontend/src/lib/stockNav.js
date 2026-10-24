import { createContext } from 'react'

// What a stock's detail needs to open another stock (#114: clicking a node in Connections): your
// holdings, and openStock(stock), which shows a holding on Positions and any other stock on Markets.
// App.jsx provides it.
export const StockNavContext = createContext({ holdings: [], openStock: null })
