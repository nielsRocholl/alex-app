import streamlit as st
from modules.kenter_module import get_kenter_data
from modules.entsoe_module import get_energy_prices
from modules.battery_module import BatterySavingsCalculator
from modules.tax_module import NetworkTaxCalculator
from utils.utils import *
from auth.authenticator import Authenticator
from datetime import datetime
import plotly.graph_objects as go
from streamlit_echarts import st_echarts
import pandas as pd

# Set page configuration
st.set_page_config(
    page_title="Energy Analyzer",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize the Authenticator
allowed_users = st.secrets["ALLOWED_USERS"].split(",")
authenticator = Authenticator(
    allowed_users=allowed_users,
    token_key=st.secrets["TOKEN_KEY"],
    client_secret=st.secrets["CLIENT_SECRET"],
    redirect_uri= "http://localhost:8501" #"https://mango2mango.streamlit.app/" #"http://localhost:8501" #
)

def recalculate_savings(battery_capacity, enable_grid_arbitrage, enable_solar_arbitrage):
    """Recalculate savings without fetching new data"""
    if 'report_data' not in st.session_state:
        return
    
    # Get cached data
    usage_df = st.session_state.report_data['usage_df']
    price_df = st.session_state.report_data['price_df']
    
    # Recalculate savings
    battery_calculator = BatterySavingsCalculator(
        battery_capacity=battery_capacity,
        enable_grid_arbitrage=enable_grid_arbitrage,
        enable_solar_arbitrage=enable_solar_arbitrage
    )
    savings = battery_calculator.arbitrage(usage_df, price_df)
    
    # Update session state
    st.session_state.report_data['savings'] = savings

def determine_time_grouping(start_date, end_date):
    """Determine appropriate time grouping based on date range"""
    days_difference = (end_date - start_date).days
    
    if days_difference <= 30:  # Less than a month
        return 'day', 'Daily'
    elif days_difference <= 90:  # 1-3 months
        return 'week', 'Weekly'
    else:  # More than 3 months
        return 'month', 'Monthly'

def group_data_by_time(df, time_unit, date_column='date'):
    """Group data by specified time unit (day, week, month)"""
    if df is None or df.empty or date_column not in df.columns:
        return df
    
    # Ensure date column is datetime
    if not pd.api.types.is_datetime64_dtype(df[date_column]):
        df[date_column] = pd.to_datetime(df[date_column])
    
    # Create a copy to avoid modifying the original
    grouped_df = df.copy()
    
    if time_unit == 'day':
        # Already daily, no grouping needed
        return grouped_df
    elif time_unit == 'week':
        # Add week start date
        grouped_df['period'] = grouped_df[date_column].dt.to_period('W').dt.start_time
    elif time_unit == 'month':
        # Add month start date
        grouped_df['period'] = grouped_df[date_column].dt.to_period('M').dt.start_time
    
    # Group by the period
    numeric_columns = grouped_df.select_dtypes(include=['number']).columns
    
    # Group and aggregate
    result = grouped_df.groupby('period')[numeric_columns].sum().reset_index()
    
    # Rename period back to original date column
    result.rename(columns={'period': date_column}, inplace=True)
    
    return result

def main():
    # Header with title in modern layout
    # Move account info to top right of main area
    header_col1, header_col2 = st.columns([3, 1])
    
    with header_col1:
        st.title("Energy Analyzer")
        st.caption("Smart Battery Solutions for Solar Systems")
    
    # Authentication check
    authenticator.check_auth()
    
    # Account info in top right
    with header_col2:
        if st.session_state.get("connected"):
            st.markdown(
                f"""
                <div style="text-align: right; padding: 10px; border-radius: 5px;">
                    <small>Logged in as: {st.session_state['user_info'].get('email', 'User')}</small><br>
                    <a href="?logout=true" target="_self">Logout</a>
                </div>
                """, 
                unsafe_allow_html=True
            )
            # Handle logout via URL parameter using the new query_params API
            if st.query_params.get("logout"):
                authenticator.logout()
                st.rerun()
        else:
            # Keep the header area clean when not logged in
            st.markdown("<div style='height: 50px;'></div>", unsafe_allow_html=True)

    # Sidebar configuration - cleaner and more organized
    with st.sidebar:
        if st.session_state.get("connected"):
            # Client selection section with better spacing
            st.markdown("## Client Data")
            meter_hierarchy = get_meter_hierarchy()

            # Connection selection with improved layout
            connection_names = list(meter_hierarchy.keys())
            selected_conn_name = st.selectbox(
                "Client Connection Point",
                options=connection_names,
                index=0,
                help="Select the client's facility connection point",
                on_change=clear_report_state
            )

            # Get connection details automatically
            if selected_conn_name:
                conn_details = meter_hierarchy[selected_conn_name]
                connection_id = conn_details['connection_id']
                main_meter = conn_details['main_meter']
                
                # Clean up client data presentation with consistent styling
                st.markdown("#### Client Details")
                if conn_details.get('address') and conn_details.get('city'):
                    st.markdown(f"**Location:** {conn_details['address']}, {conn_details['city']}")
                
                # Display GTV in a consistent format
                if conn_details.get('gtv'):
                    st.markdown(f"**Contracted Capacity:** {conn_details.get('gtv', 'N/A')} kW")
            
            st.markdown("---")
            
            # Battery settings in an expander for cleaner UI
            with st.expander("Battery Settings", expanded=True):
                battery_capacity = st.slider(
                    "Battery Capacity (kWh)",
                    min_value=1,
                    max_value=1000,
                    value=100,
                    step=1,
                    help="Select the capacity of the battery storage system"
                )
                
                # Toggle buttons stacked vertically
                enable_solar_arbitrage = st.toggle(
                    "Solar Storage",
                    value=True,
                    help="Store excess solar energy to use during expensive periods"
                )
                
                enable_grid_arbitrage = st.toggle(
                    "Grid Arbitrage",
                    value=True,
                    help="Buy cheap grid energy to use during expensive periods"
                )
                    
                # If any settings change and we have data, recalculate
                if 'report_data' in st.session_state:
                    current_settings = (
                        battery_capacity,
                        enable_grid_arbitrage,
                        enable_solar_arbitrage
                    )
                    if 'last_settings' not in st.session_state:
                        st.session_state.last_settings = current_settings
                    
                    if current_settings != st.session_state.last_settings:
                        recalculate_savings(battery_capacity, enable_grid_arbitrage, enable_solar_arbitrage)
                        st.session_state.last_settings = current_settings
            
            # Network operator in its own section
            with st.expander("Network & Grid", expanded=True):
                network_operator = st.selectbox(
                    "Network Operator",
                    options=NetworkTaxCalculator.NETWORK_OPERATORS,
                    index=0,
                    help="Select the client's network operator for accurate tax calculations"
                )
        else:
            st.info("Please log in to access the analyzer")
            
            # Add a big, visible login button in the sidebar
            auth_url = authenticator.get_auth_url()
            if st.button("Login with Google", type="primary", use_container_width=True):
                st.switch_page(auth_url)

    # Main content area - Only visible for authenticated users
    if st.session_state.get("connected"):
        # Welcome message with clear next steps
        # st.markdown("### Welcome to the Battery Analysis Tool")
        # st.info("Select a client connection and date range in the sidebar, then click 'Generate Report' to analyze potential battery savings.")
        
        # Analysis Period section moved from sidebar to main content area
        st.markdown("## Analysis Period")
        
        # Create a 3-column layout for the Analysis Period section
        date_col1, date_col2, date_col3 = st.columns([1, 1, 1])
        
        # Calculate default dates: yesterday and 15 days before yesterday
        yesterday = datetime.now().date() - pd.Timedelta(days=1)
        default_start_date = yesterday - pd.Timedelta(days=14)
        
        # Date inputs in main content area
        with date_col1:
            start_date = st.date_input(
                "Start Date", 
                value=default_start_date, 
                help="Select the beginning of the analysis period"
            )
        
        with date_col2:
            end_date = st.date_input(
                "End Date", 
                value=yesterday, 
                help="Select the end of the analysis period"
            )
        
        # Generate Report button in main content area
        with date_col3:
            st.markdown("<br>", unsafe_allow_html=True)  # Add some spacing
            generate_report = st.button("Generate Report", type="primary", use_container_width=True)
        
        st.markdown("---")
        
        # Process the Generate Report button click
        if generate_report:
            st.session_state.show_report = True
            if start_date and end_date and selected_conn_name:
                valid, error_message = validate_dates(start_date, end_date)
                if not valid:
                    st.error(error_message)
                    st.session_state.show_report = False
                    return
                
                try:
                    with st.spinner('Analyzing energy data and calculating savings...'):
                        # Fetch data
                        usage_df = get_kenter_data(
                            start_date.strftime('%Y-%m-%d'),
                            end_date.strftime('%Y-%m-%d'),
                            connection_id=connection_id,
                            metering_point=main_meter,
                            interval='15min'
                        )
                        
                        price_df = get_energy_prices(
                            start_date.strftime('%Y-%m-%d'),
                            end_date.strftime('%Y-%m-%d')
                        )
                        
                        # Get GTV for tax calculation
                        gtv_str = conn_details.get('gtv', 'N/A')
                        try:
                            gtv = float(gtv_str)
                        except (ValueError, TypeError):
                            st.warning("Could not determine GTV for tax calculations. Using default high rate.")
                            gtv = 0  # This will result in using the low_gtv (higher) tax rate
                        
                        # Calculate network tax
                        tax_calculator = NetworkTaxCalculator()
                        tax_df = tax_calculator.calculate_tax(
                            usage_df,
                            network_operator,
                            gtv
                        )
                        
                        # Calculate metrics including tax
                        daily_costs = calculate_daily_costs(usage_df, price_df, tax_df)
                        battery_calculator = BatterySavingsCalculator(
                            battery_capacity=battery_capacity,
                            enable_grid_arbitrage=enable_grid_arbitrage,
                            enable_solar_arbitrage=enable_solar_arbitrage
                        )
                        savings = battery_calculator.arbitrage(usage_df, price_df)
                        
                        # Determine time grouping based on date range
                        time_unit, time_label = determine_time_grouping(start_date, end_date)
                        
                        # Store results in session state
                        st.session_state.report_data = {
                            'usage_df': usage_df,
                            'price_df': price_df,
                            'tax_df': tax_df,
                            'daily_costs': daily_costs,
                            'savings': savings,
                            'generated_at': datetime.now(),
                            'time_unit': time_unit,
                            'time_label': time_label
                        }
                        
                except Exception as e:
                    if 'timestamp' in str(e):
                        st.error("No data available for the selected meter and date range.")
                    else:
                        st.error(f"Error generating report: {str(e)}")
                    st.session_state.show_report = False
                    st.session_state.pop('report_data', None)
                    return

        # Initialize the show_report state if it doesn't exist
        if 'show_report' not in st.session_state:
            st.session_state.show_report = False

        # Display report content organized in tabs for better navigation
        if st.session_state.show_report and 'report_data' in st.session_state:
            report_data = st.session_state.report_data
            usage_df = report_data['usage_df']
            price_df = report_data['price_df']
            tax_df = report_data['tax_df']
            daily_costs = report_data['daily_costs']
            savings = report_data['savings']
            time_unit = report_data.get('time_unit', 'day')
            time_label = report_data.get('time_label', 'Daily')
            
            # Group data based on time unit if needed
            if time_unit != 'day':
                daily_costs = group_data_by_time(daily_costs, time_unit)
                savings = group_data_by_time(savings, time_unit, date_column='timestamp')
            
            st.markdown("---")
            
            # Summary metrics at the top for immediate insights
            total_costs = daily_costs['cost'].sum()
            total_tax = daily_costs['tax'].sum()
            total_energy_cost = total_costs - total_tax
            total_net_savings = savings['net_savings'].sum()
            total_grid_arbitrage = savings['grid_arbitrage_savings'].sum()
            total_lost_revenue = savings['lost_revenue'].sum()
            total_combined_savings = total_net_savings + total_grid_arbitrage - total_lost_revenue
            savings_percentage = (total_combined_savings / total_costs * 100) if total_costs > 0 else 0
            final_cost = total_costs - total_combined_savings
            
            # Key metrics in a prominent row
            st.markdown("## Battery Impact Summary")
            metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
            
            with metric_col1:
                st.metric(
                    "Current Energy Costs", 
                    f"€{total_costs:.2f}", 
                    delta=None,
                    help="Total energy costs without a battery system"
                )
            
            with metric_col2:
                st.metric(
                    "Potential Savings", 
                    f"€{total_combined_savings:.2f}", 
                    delta=f"{savings_percentage:.1f}%",
                    delta_color="normal",
                    help="Total savings with the selected battery configuration"
                )
            
            with metric_col3:
                st.metric(
                    "New Energy Costs", 
                    f"€{final_cost:.2f}", 
                    delta=f"-{savings_percentage:.1f}%",
                    delta_color="inverse",
                    help="Total energy costs after implementing the battery system"
                )
                
            with metric_col4:
                monthly_savings = total_combined_savings / ((end_date - start_date).days / 30)
                st.metric(
                    "Monthly Savings", 
                    f"€{monthly_savings:.2f}",
                    help="Estimated monthly savings with the battery system"
                )
            
            # Organize detailed content in tabs with new order
            report_tabs = st.tabs([
                "Savings Analysis", 
                "Detailed Metrics",
                "Battery ROI",
                "Energy Flow"
            ])
            
            # Tab 1: Savings Analysis
            with report_tabs[0]:
                st.markdown(f"### Battery Savings Potential ({time_label})")
                
                # Display contextual information above the chart
                explanation_col1, explanation_col2 = st.columns([3, 1])
                with explanation_col1:
                    st.markdown(f"""
                    This chart shows your client's **{time_label.lower()} energy costs** with and without a battery system:
                    - The **coral bars** show current costs without a battery
                    - The **blue line** shows costs after battery savings
                    - The **teal trend line** shows the savings pattern over time
                    """)
                
                # Create the ECharts options - use the same function but with grouped data
                echarts_options = create_echarts_cost_savings_plot(daily_costs, savings)
                
                # Display the chart with additional height for better visualization
                try:
                    st_echarts(options=echarts_options, height="500px", key="cost_savings_chart")
                except Exception as e:
                    st.error(f"Error displaying ECharts: {str(e)}")
                    
                    # Fallback to plotly
                    st.info("Displaying fallback visualization...")
                    merged_data = pd.merge(
                        daily_costs,
                        savings,
                        left_on='date',
                        right_on='timestamp',
                        how='outer'
                    )
                    
                    # Calculate final cost
                    merged_data['final_cost'] = merged_data['cost'] - merged_data['net_savings'] - merged_data['grid_arbitrage_savings']
                    
                    # Create a simple plotly bar chart
                    fig = go.Figure()
                    
                    # Add original cost bars
                    fig.add_trace(go.Bar(
                        x=merged_data['date'],
                        y=merged_data['cost'],
                        name='Current Cost',
                        marker_color='#FF6B6B'
                    ))
                    
                    # Add final cost line
                    fig.add_trace(go.Scatter(
                        x=merged_data['date'],
                        y=merged_data['final_cost'],
                        name='Final Cost',
                        line=dict(color='#4361EE', width=3)
                    ))
                    
                    fig.update_layout(
                        title=f"{time_label} Cost Comparison",
                        xaxis_title="Date",
                        yaxis_title="Cost (€)",
                        legend_title="Legend",
                        height=500,
                        template="plotly_white"
                    )
                    
                    st.plotly_chart(fig, use_container_width=True)
            
                st.markdown(f"### {time_label} Savings Breakdown")
                st.markdown(f"""
                This chart shows how your client's savings are calculated ({time_label.lower()} aggregation):
                - **Solar Savings**: Money saved by using stored solar energy
                - **Grid Arbitrage**: Money saved by buying cheap electricity and using it during expensive periods
                - **Lost Revenue**: Money that could have been earned by selling excess solar energy back to the grid
                - **Net Savings**: Total savings after all factors are considered
                """)
                
                # Create the savings breakdown chart with grouped data
                breakdown_options = create_savings_breakdown_chart(savings)
                
                # Display the chart
                try:
                    st_echarts(options=breakdown_options, height="400px", key="savings_breakdown_chart")
                except Exception as e:
                    st.error(f"Error displaying savings breakdown chart: {str(e)}")
            
            # Tab 2: Detailed Metrics (moved up)
            with report_tabs[1]:
                st.markdown("### Energy & Cost Details")
                
                # Two-column layout for metrics
                detail_col1, detail_col2 = st.columns(2)
                
                with detail_col1:
                    st.markdown("#### Current Cost Structure")
                    # Create pie chart for cost breakdown
                    fig = go.Figure()
                    fig.add_trace(go.Pie(
                        labels=['Energy Cost', 'Network Tax'],
                        values=[total_energy_cost, total_tax],
                        hole=0.6,
                        marker_colors=['#1b6cbb', '#d97857'],
                        textinfo='label+percent',
                        hoverinfo='label+value+percent',
                        hovertemplate='<b>%{label}</b><br>€%{value:.2f}<br>%{percent}'
                    ))
                    fig.update_layout(
                        showlegend=False,
                        height=300,
                        margin=dict(t=0, b=0, l=0, r=0),
                        annotations=[dict(text=f'€{total_costs:.2f}', x=0.5, y=0.5, font_size=16, showarrow=False)]
                    )
                    st.plotly_chart(fig, use_container_width=True)

                with detail_col2:
                    st.markdown("#### Energy Metrics")
                    
                    # Calculate key metrics
                    total_supply = usage_df[usage_df['type'] == 'supply']['value'].sum()
                    total_return = usage_df[usage_df['type'] == 'return']['value'].sum()
                    avg_price = price_df['price'].mean()
                    
                    # Display in a more organized format using metrics
                    energy_col1, energy_col2 = st.columns(2)
                    with energy_col1:
                        st.metric("Grid Energy Used", f"{total_supply:.1f} kWh", help="Energy bought from the grid")
                        st.metric("Average Price", f"€{avg_price:.3f}/kWh", help="Average price paid for grid energy")
                    with energy_col2:
                        st.metric("Solar Energy Returned", f"{total_return:.1f} kWh", help="Energy sold back to the grid")
                        conn_details = meter_hierarchy[selected_conn_name]
                        gtv = conn_details.get('gtv', 'N/A')
                        st.metric("Contracted Capacity", f"{gtv} kW", help="Determines network costs & capacity")
                
                # Savings breakdown in a cleaner format
                st.markdown("#### Savings Breakdown")
                savings_col1, savings_col2, savings_col3 = st.columns(3)
                
                with savings_col1:
                    st.metric(
                        "Solar Storage Savings", 
                        f"€{total_net_savings:.2f}", 
                        help="Savings from storing solar energy"
                    )
                
                with savings_col2:
                    st.metric(
                        "Grid Arbitrage Savings", 
                        f"€{total_grid_arbitrage:.2f}", 
                        help="Savings from smart grid energy buying"
                    )
                
                with savings_col3:
                    st.metric(
                        "Lost Solar Revenue", 
                        f"-€{total_lost_revenue:.2f}", 
                        delta=f"-{(total_lost_revenue/total_costs*100):.1f}%" if total_costs > 0 else None,
                        delta_color="inverse",
                        help="Potential income lost from not selling solar back to grid"
                    )
            
            # Tab 3: Battery ROI (moved up)
            with report_tabs[2]:
                st.markdown("### Return on Investment")
                
                # Constants for ROI calculation
                avg_battery_cost_per_kwh = 800  # € per kWh
                estimated_installation_cost = 2000  # €
                estimated_battery_lifetime = 10  # years
                
                # Calculate ROI metrics
                battery_cost = battery_capacity * avg_battery_cost_per_kwh + estimated_installation_cost
                yearly_savings = monthly_savings * 12
                payback_years = battery_cost / yearly_savings if yearly_savings > 0 else float('inf')
                lifetime_savings = yearly_savings * estimated_battery_lifetime
                roi_percentage = (lifetime_savings - battery_cost) / battery_cost * 100 if battery_cost > 0 else 0
                
                # Display ROI information
                roi_col1, roi_col2 = st.columns(2)
                
                with roi_col1:
                    st.markdown("#### Investment Overview")
                    st.metric("Battery System Cost", f"€{battery_cost:,.2f}", help="Estimated cost for the battery system")
                    st.metric("Yearly Savings", f"€{yearly_savings:,.2f}", help="Estimated yearly savings")
                    st.metric("Payback Period", f"{payback_years:.1f} years", help="Time until the battery pays for itself")
                
                with roi_col2:
                    st.markdown("#### Long-Term Benefits")
                    st.metric("Battery Lifetime", f"{estimated_battery_lifetime} years", help="Estimated battery system lifetime")
                    st.metric("Lifetime Savings", f"€{lifetime_savings:,.2f}", help="Total savings over battery lifetime")
                    st.metric("Return on Investment", f"{roi_percentage:.1f}%", help="ROI percentage over battery lifetime")
                
                # Value proposition explanation in collapsible section
                with st.expander("Value Proposition Details", expanded=True):
                    st.markdown("""
                    ### Key Benefits for Your Client
                    
                    #### Financial Benefits
                    - **Reduced Energy Bills**: Save on monthly electricity expenses
                    - **Protection from Price Spikes**: Buffer against volatile energy prices
                    - **Tax Advantages**: Potential tax benefits for renewable energy investments
                    
                    #### System Benefits
                    - **Energy Independence**: Less reliance on the grid
                    - **Backup Power**: Critical systems can remain operational during outages
                    - **Extended Solar Value**: Get more value from existing solar investment
                    
                    #### Environmental Benefits
                    - **Reduced Carbon Footprint**: More effective use of clean solar energy
                    - **Support Grid Stability**: Help balance the grid by reducing peak demand
                    - **Future-Proof Investment**: Compatible with emerging energy management technologies
                    """)
            
            # Tab 4: Energy Flow (moved to end)
            with report_tabs[3]:
                st.markdown("### Energy Flow & Electricity Prices")
                st.markdown("""
                This chart shows the relationship between energy consumption, production, and electricity prices:
                - **Blue bars**: Energy consumed from the grid
                - **Green bars**: Solar energy returned to the grid
                - **Orange line**: Electricity price variations throughout the day
                """)
                fig = create_plot(usage_df, price_df)
                st.plotly_chart(fig, use_container_width=True)
            
            # Report footer with timestamp
            st.markdown("---")
            st.caption(f"Report generated: {report_data['generated_at'].strftime('%Y-%m-%d %H:%M:%S')}")
                
        elif not st.session_state.show_report:
            st.info("Select your client's connection and date range in the sidebar, then click 'Generate Report' to begin the analysis.")
    
    else:
        # Display demo message for users who haven't logged in
        st.markdown("### Smart Battery Analysis Tool")
        st.markdown("""
        This tool helps you demonstrate the financial benefits of adding battery storage to your clients' solar systems.
        
        **Features:**
        - Calculate potential cost savings
        - Analyze solar storage efficiency
        - Demonstrate grid arbitrage benefits
        - Generate professional client reports
        
        Please log in using the button in the sidebar to access the full functionality.
        """)

if __name__ == "__main__":
    main()