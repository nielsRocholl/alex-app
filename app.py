import streamlit as st
from modules.kenter_module import get_kenter_data
from modules.entsoe_module import get_energy_prices
from modules.battery_module import BatterySavingsCalculator
from utils.utils import *
from auth.authenticator import Authenticator

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
    redirect_uri= "https://nielsrocholl.streamlit.app/"  #"http://localhost:8501"
)

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
                help="Select your facility's connection point"
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

        # Add fetch button
        if st.button("🚀 Generate Report"):
            if start_date and end_date and selected_conn_name:
                valid, error_message = validate_dates(start_date, end_date)
                
                if not valid:
                    st.error(error_message)
                    return
                
                try:
                    with st.spinner('Crunching numbers...'):
                        # Fetch data
                        usage_df = get_kenter_data(
                            start_date.strftime('%Y-%m-%d'),
                            end_date.strftime('%Y-%m-%d'),
                            connection_id=connection_id,  # From the selected connection details
                            metering_point=main_meter,    # Automatically use main meter
                            interval='15min'
                        )
                        
                        price_df = get_energy_prices(
                            start_date.strftime('%Y-%m-%d'),
                            end_date.strftime('%Y-%m-%d')
                        )    
                        
                        # Calculate metrics
                        daily_costs = calculate_daily_costs(usage_df, price_df)
                        battery_calculator = BatterySavingsCalculator()
                        savings = battery_calculator.arbitrage(usage_df, price_df)
                        
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
                        
                        # Key metrics cards - Revised Summary Statistics
                        st.markdown("### 📊 Your Battery Savings Potential")

                        # Calculate values
                        total_costs = daily_costs['cost'].sum()
                        total_savings = savings['savings'].sum()
                        savings_percentage = (total_savings / total_costs * 100) if total_costs > 0 else 0
                        total_supply = usage_df[usage_df['type'] == 'supply']['value'].sum()
                        total_return = usage_df[usage_df['type'] == 'return']['value'].sum()
                        avg_price = price_df['price'].mean()

                        # Display metrics
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric(
                                "💰 Costs Without Battery", 
                                f"€{total_costs:.2f}",
                                help="Your total electricity bill if you DON'T have a battery"
                            )
                        with col2:
                            st.metric(
                                "🔋 Savings With Battery", 
                                f"€{total_savings:.2f}",
                                help="Money you COULD save by storing solar energy in a battery",
                                delta=f"{savings_percentage:.1f}% savings"  # Adds visual emphasis
                            )
                        with col3:
                            st.metric(
                                "☀️ Solar Energy Used", 
                                f"{total_return:.1f} kWh",
                                help="Clean energy produced by your solar panels"
                            )

                        # Energy statistics - Revised Energy Overview
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
                                                
                except Exception as e:
                    if 'timestamp' in str(e):
                        st.error("No data available for selected meter")
                    else:
                        st.error(f"Error generating report: {str(e)}")
        else:
            st.info("Select dates and click 'Generate Report' to begin")
    else:
        st.warning("🔒 Please log in to access the energy analyzer")

if __name__ == "__main__":
    main()