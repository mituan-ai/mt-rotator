import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { getInstanceByDom, init, use as registerECharts, type EChartsCoreOption } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'

registerECharts([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

export function Chart({ option, height = 340 }: { option: EChartsCoreOption; height?: number }) {
    const element = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (!element.current) return
        const chart = init(element.current)
        const observer = new ResizeObserver(() => chart.resize())
        observer.observe(element.current)
        return () => {
            observer.disconnect()
            chart.dispose()
        }
    }, [])

    useEffect(() => {
        const chart = element.current ? getInstanceByDom(element.current) || init(element.current) : null
        chart?.setOption(option, { notMerge: true })
    }, [option])

    return <div ref={element} style={{ height }} role="img" aria-label="绩效曲线" />
}
