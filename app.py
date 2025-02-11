import streamlit as st
from modules.kenter_module import get_kenter_data
from modules.entsoe_module import get_energy_prices
from modules.battery_module import BatterySavingsCalculator
from utils.utils import *
from auth.authenticator import Authenticator
from datetime import datetime

# Set page configuration
st.set_page_config(
    page_title="Energy Analyzer",
    page_icon="⚡",
    layout="wide"
)

# Initialize the Authenticator
allowed_users = st.secrets["ALLOWED_USERS"].split(",")
authenticator = Authenticator(
    allowed_users=allowed_users,
    token_key=st.secrets["TOKEN_KEY"],
    client_secret=st.secrets["CLIENT_SECRET"],
    redirect_uri= "https://nielsrocholl.streamlit.app/" #"http://localhost:8501"
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

def main():
    st.title("⚡ Energy Analyzer")
    authenticator.check_auth()

    # Show login/logout buttons in the sidebar
    with st.sidebar:
        if st.session_state.get("connected"):
            if st.button("Log out", use_container_width=True):
                authenticator.logout()
                st.rerun()
            
            st.subheader("Analysis Settings")
            
            # Battery capacity input
            battery_capacity = st.number_input(
                "Battery Capacity (kWh)",
                min_value=1,
                max_value=1000,
                value=100,
                step=1,
                format="%d",
                help="Enter the capacity of your battery storage system in kWh"
            )
            
            enable_solar_arbitrage = st.toggle(
                "Enable Solar Storage",
                value=True,
                help="Store excess solar energy to use during expensive periods"
            )
            enable_grid_arbitrage = st.toggle(
                "Enable Grid Arbitrage",
                value=False,
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
            
            # Plot selection
            selected_plots = st.multiselect(
                "Choose visualizations to display:",
                options=["Energy Flow & Prices", "Cost Savings"],
                default=["Cost Savings"],
                help="Select which charts to show in the analysis"
            )
            
            st.markdown("---")
            st.subheader("Meter Selection")
            meter_hierarchy = get_meter_hierarchy()

            # Connection selection with formatted names
            connection_names = list(meter_hierarchy.keys())
            selected_conn_name = st.selectbox(
                "Connection Point",
                options=connection_names,
                index=0,
                help="Select your facility's connection point",
                on_change=clear_report_state
            )

            # Get connection details automatically
            if selected_conn_name:
                conn_details = meter_hierarchy[selected_conn_name]
                connection_id = conn_details['connection_id']
                main_meter = conn_details['main_meter']
        else:
            auth_url = authenticator.get_auth_url()
            st.link_button("Login with Google", auth_url, use_container_width=True)

    # Main content for authenticated users
    if st.session_state.get("connected"):
        st.write(f"Welcome, {st.session_state['user_info'].get('email', 'User')}! 👋")
        st.markdown("---")

        # Date inputs
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", help="Select analysis start date")
        with col2:
            end_date = st.date_input("End Date", help="Select analysis end date")

        # Initialize the show_report state if it doesn't exist
        if 'show_report' not in st.session_state:
            st.session_state.show_report = False

        # Add generate report button
        if st.button("🚀 Generate Report"):
            st.session_state.show_report = True
            if start_date and end_date and selected_conn_name:
                valid, error_message = validate_dates(start_date, end_date)
                if not valid:
                    st.error(error_message)
                    st.session_state.show_report = False
                    return
                
                try:
                    with st.spinner('Crunching numbers...'):
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
                        
                        # Calculate metrics
                        daily_costs = calculate_daily_costs(usage_df, price_df)
                        battery_calculator = BatterySavingsCalculator(
                            battery_capacity=battery_capacity,
                            enable_grid_arbitrage=enable_grid_arbitrage,
                            enable_solar_arbitrage=enable_solar_arbitrage
                        )
                        savings = battery_calculator.arbitrage(usage_df, price_df)
                        
                        # Store results in session state
                        st.session_state.report_data = {
                            'usage_df': usage_df,
                            'price_df': price_df,
                            'daily_costs': daily_costs,
                            'savings': savings,
                            'generated_at': datetime.now()
                        }
                        
                except Exception as e:
                    if 'timestamp' in str(e):
                        st.error("No data available for selected meter")
                    else:
                        st.error(f"Error generating report: {str(e)}")
                    st.session_state.show_report = False
                    st.session_state.pop('report_data', None)
                    return

        # Display report if show_report is True and we have data
        if st.session_state.show_report and 'report_data' in st.session_state:
            report_data = st.session_state.report_data
            usage_df = report_data['usage_df']
            price_df = report_data['price_df']
            daily_costs = report_data['daily_costs']
            savings = report_data['savings']
            
            # Show selected visualizations
            if "Energy Flow & Prices" in selected_plots:
                st.markdown("## 📈 Energy Flow & Electricity Prices")
                fig = create_plot(usage_df, price_df)
                st.plotly_chart(fig, use_container_width=True)
                st.markdown("---")
            
            if "Cost Savings" in selected_plots:
                st.markdown("## 💰 Battery Savings Potential")
                cost_savings_fig = create_cost_savings_plot(daily_costs, savings)
                st.plotly_chart(cost_savings_fig, use_container_width=True)
                st.markdown("---")
            
            # Key metrics cards
            st.markdown("### 📊 Your Battery Savings Potential")
            total_costs = daily_costs['cost'].sum()
            total_gross_savings = savings['gross_savings'].sum()
            total_lost_revenue = savings['lost_revenue'].sum()
            total_net_savings = savings['net_savings'].sum()
            total_grid_arbitrage = savings['grid_arbitrage_savings'].sum()
            total_combined_savings = total_net_savings + total_grid_arbitrage
            savings_percentage = (total_combined_savings / total_costs * 100) if total_costs > 0 else 0
            total_supply = usage_df[usage_df['type'] == 'supply']['value'].sum()
            total_return = usage_df[usage_df['type'] == 'return']['value'].sum()
            avg_price = price_df['price'].mean()

            # Display metrics in two rows
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric(
                    "💰 Current Costs", 
                    f"€{total_costs:.2f}",
                    help="Your total electricity costs with current setup"
                )
            with col2:
                st.metric(
                    "🌞 Solar Storage Savings", 
                    f"€{total_net_savings:.2f}",
                    help="Net savings from storing and using your solar energy"
                )
            with col3:
                st.metric(
                    "⚡ Grid Arbitrage Savings", 
                    f"€{total_grid_arbitrage:.2f}",
                    help="Additional savings from buying cheap grid energy"
                )

            # Second row of metrics
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric(
                    "💹 Total Combined Savings", 
                    f"€{total_combined_savings:.2f}",
                    delta=f"{savings_percentage:.1f}% of costs",
                    help="Total savings from both solar storage and grid arbitrage"
                )
            with col2:
                st.metric(
                    "📉 Lost Solar Revenue", 
                    f"-€{total_lost_revenue:.2f}",
                    help="Revenue lost from not selling solar energy back to grid"
                )
            with col3:
                st.metric(
                    "💸 Final Costs", 
                    f"€{(total_costs - total_combined_savings):.2f}",
                    help="Your estimated costs after all optimizations"
                )

            # Energy statistics
            st.markdown("### ⚡ Energy Snapshot")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric(
                    "🔌 Grid Energy Used", 
                    f"{total_supply:.1f} kWh",
                    help="Energy bought from the power company"
                )
            with col2:
                st.metric(
                    "💡 Average Electricity Price", 
                    f"€{avg_price:.3f}/kWh",
                    help="Typical price you paid for grid energy"
                )
            with col3:
                st.metric(
                    "📆 Period Covered", 
                    f"{start_date.strftime('%d %b')} - {end_date.strftime('%d %b')}",
                    help="Analysis time range"
                )
            
            # Add refresh button with timestamp
            refresh_col, ts_col = st.columns([1,3])
            with refresh_col:
                if st.button("🔄 Refresh Results", help="Recalculate with latest data"):
                    st.session_state.show_report = False
                    st.rerun()
            with ts_col:
                st.caption(f"Last updated: {report_data['generated_at'].strftime('%Y-%m-%d %H:%M:%S')}")
        
        elif not st.session_state.show_report:
            st.info("Select dates and click 'Generate Report' to begin")
        
    else:
        st.warning("🔒 Please log in to access the energy analyzer")

if __name__ == "__main__":
    main()