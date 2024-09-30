import discord
from discord.ext import commands, tasks
from discord import app_commands
from collections import defaultdict
import re
import asyncio
from datetime import datetime, timedelta
import sqlite3

TOKEN = 'KOS OMAK'
SPECIFIC_CHANNEL_ID = 1279570358789214339
NOTIFICATION_CHANNEL_ID = 1182246453964443652
ROLE_ID = 1189132183806427219
TRIGGER_CHANNEL_ID = 1279569386696605749
REACTION_EMOJI_NAME = 'verify_purple'
REACTION_EMOJI_ID = 1270224226439135263
X_EMOJI_NAME = 'x_'
X_EMOJI_ID = 1275258066094264360
INITIAL_EMOJI_NAME = 'loadingx'
INITIAL_EMOJI_ID = 1275402033381507163  # Replace with the actual emoji ID

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.members = True
intents.message_content = True

client = commands.Bot(command_prefix="!", intents=intents)

mention_counts = defaultdict(int)
original_sender_counts = defaultdict(int)
processed_messages = set()
trigger_messages = defaultdict(list)
verification_enabled = False
triggering_enabled = False


# Add SQLite connection
conn = sqlite3.connect('bot_database.db')
cursor = conn.cursor()

# Create tables if they don't exist
cursor.execute('''
    CREATE TABLE IF NOT EXISTS helpers (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        count INTEGER
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS requesters (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        count INTEGER
    )
''')
conn.commit()
# Store the message ID and timestamp for each message in the trigger channel
unverified_messages = {}


# Add this dictionary to store the last trigger message time for each user
last_trigger_message = {}

# Modify your on_message event to track trigger channel messages

@client.event
async def on_ready():
    print(f'Logged in as {client.user}')
    await client.tree.sync()
    check_unverified_messages.start()  # Start the background task

@client.event
async def on_message(message):
    if message.channel.id == TRIGGER_CHANNEL_ID:
        last_trigger_message[message.author.id] = datetime.now()


    if message.author == client.user:
        return

    global verification_enabled, triggering_enabled


    # ... rest of your existing on_message code ...

    if triggering_enabled and message.channel.id == TRIGGER_CHANNEL_ID:
        trigger_messages[message.author.id].append((message.id, message.created_at))
        notification_channel = client.get_channel(NOTIFICATION_CHANNEL_ID)
        if notification_channel:
            role = message.guild.get_role(ROLE_ID)
            embed = discord.Embed(title="Help Request", color=0x400080)
            embed.add_field(name="User", value=f"{message.author.display_name} asking for help", inline=False)
            embed.add_field(name="Message", value=message.content, inline=False)
            await rate_limited_send(notification_channel, role.mention, embed)
        
        # Add the message to the unverified_messages dictionary
        unverified_messages[message.id] = datetime.now()

        # Add the initial emoji reaction
        initial_emoji = discord.PartialEmoji(name=INITIAL_EMOJI_NAME, id=INITIAL_EMOJI_ID)
        try:
            await message.add_reaction(initial_emoji)
        except discord.errors.HTTPException as e:
            print(f"Failed to add initial emoji: {e}")


    if verification_enabled and message.channel.id == SPECIFIC_CHANNEL_ID:
        await check_and_react_to_trigger_messages(message)

    if message.content.startswith('!leaderboard'):
        parts = message.content.split()

        if len(parts) == 1:
            await process_mentions(message.channel, False)
        elif len(parts) == 2:
            mention = parts[1]
            user_id = int(re.findall(r'\d+', mention)[0])
            user = message.guild.get_member(user_id)
            if user:
                await process_mentions(message.channel, True, user)
            else:
                await message.channel.send('User not found.')

async def rate_limited_send(channel, content=None, embed=None):
    try:
        await channel.send(content=content, embed=embed)
    except discord.errors.HTTPException as e:
        if e.status == 429:
            retry_after = e.retry_after
            print(f'Rate limited. Retrying after {retry_after} seconds.')
            await asyncio.sleep(retry_after)
            await channel.send(content=content, embed=embed)
        else:
            raise e
@client.tree.command(name="enable_verification", description="Enable verification and triggering")
@app_commands.checks.has_permissions(administrator=True)
async def enable_verification(interaction: discord.Interaction):
    global verification_enabled, triggering_enabled
    
    verification_enabled = True
    triggering_enabled = True
    await interaction.response.send_message('Verification and triggering have been enabled.', ephemeral=True)

@client.tree.command(name="disable_verification", description="Disable verification and triggering")
@app_commands.checks.has_permissions(administrator=True)
async def disable_verification(interaction: discord.Interaction):
    global verification_enabled, triggering_enabled
    
    verification_enabled = False
    triggering_enabled = False
    await interaction.response.send_message('Verification and triggering have been disabled.', ephemeral=True)

# Error handler for permission checks
@enable_verification.error
@disable_verification.error
async def verification_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
    else:
        await interaction.response.send_message("An error occurred while processing the command.", ephemeral=True)
        print(f"Error in verification command: {str(error)}")


async def check_and_react_to_trigger_messages(message):
    for embed in message.embeds:
        if embed.type == 'rich' and embed.fields:
            thank_you_field = next((field for field in embed.fields if field.name == "Thank You"), None)
            if thank_you_field:
                thanker_name = thank_you_field.value.split("from ")[-1].strip()
                
                for user_id, messages in trigger_messages.items():
                    user = message.guild.get_member(user_id)
                    if user and user.name.lower() == thanker_name.lower():
                        for msg_id, timestamp in messages:
                            try:
                                trigger_message = await client.get_channel(TRIGGER_CHANNEL_ID).fetch_message(msg_id)

                                # Check if the message already has the x_emoji or reaction_emoji
                                has_x_emoji = any(reaction.emoji == discord.PartialEmoji(name=X_EMOJI_NAME, id=X_EMOJI_ID) for reaction in trigger_message.reactions)
                                has_reaction_emoji = any(reaction.emoji == discord.PartialEmoji(name=REACTION_EMOJI_NAME, id=REACTION_EMOJI_ID) for reaction in trigger_message.reactions)

                                if has_x_emoji or has_reaction_emoji:
                                    # Skip the message if it already has the x_emoji or reaction_emoji
                                    continue

                                # Remove the initial emoji
                                initial_emoji = discord.PartialEmoji(name=INITIAL_EMOJI_NAME, id=INITIAL_EMOJI_ID)
                                await trigger_message.remove_reaction(initial_emoji, client.user)
                                
                                emoji = discord.PartialEmoji(name=REACTION_EMOJI_NAME, id=REACTION_EMOJI_ID)
                                await trigger_message.add_reaction(emoji)
                                
                                # Remove the message from the unverified_messages dict
                                if msg_id in unverified_messages:
                                    del unverified_messages[msg_id]
                                
                                trigger_messages[user_id].remove((msg_id, timestamp))
                            except discord.errors.NotFound:
                                print(f'Message with ID {msg_id} not found in trigger channel.')
                            except discord.errors.HTTPException as e:
                                print(f"Failed to modify reactions: {e}")
                        break

async def process_mentions(channel, specific_user_check=False, specific_user=None):
    if specific_user_check and specific_user:
        helper_count = get_helper_count(specific_user.id)
        requester_count = get_requester_count(specific_user.id)
        await channel.send(f'{specific_user.display_name} has helped {helper_count} times and requested for help {requester_count} times.')
    else:
        top_helpers = get_top_helpers()
        top_requesters = get_top_requesters()

        embed = discord.Embed(title="Top Helpers and Requesters Scoreboard", color=0x400080)

        if top_helpers:
            embed.add_field(
                name="Top 10 Helpers",
                value='\n'.join(f"{i + 1}. {username}: {count} points" for i, (username, count) in enumerate(top_helpers)),
                inline=False
            )

        if top_requesters:
            embed.add_field(
                name="Top 10 Requesters",
                value='\n'.join(f"{i + 1}. {username}: {count} times" for i, (username, count) in enumerate(top_requesters)),
                inline=False
            )

        if not top_helpers and not top_requesters:
            embed.add_field(name="No Data", value="There is no data available yet.", inline=False)

        try:
            await channel.send(embed=embed)
        except discord.errors.HTTPException as e:
            if e.status == 429:
                retry_after = e.retry_after
                print(f'Rate limited. Retrying after {retry_after} seconds.')
                await asyncio.sleep(retry_after)
                await channel.send(embed=embed)
            else:
                raise e
            
def update_helper_count(user_id, username, count):
    cursor.execute('''
        INSERT OR REPLACE INTO helpers (user_id, username, count)
        VALUES (?, ?, COALESCE((SELECT count FROM helpers WHERE user_id = ?) + ?, ?))
    ''', (user_id, username, user_id, count, count))
    conn.commit()

def update_requester_count(user_id, username, count):
    cursor.execute('''
        INSERT OR REPLACE INTO requesters (user_id, username, count)
        VALUES (?, ?, COALESCE((SELECT count FROM requesters WHERE user_id = ?) + ?, ?))
    ''', (user_id, username, user_id, count, count))
    conn.commit()

def get_helper_count(user_id):
    cursor.execute('SELECT count FROM helpers WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 0

def get_requester_count(user_id):
    cursor.execute('SELECT count FROM requesters WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 0

def get_top_helpers():
    cursor.execute('SELECT username, count FROM helpers ORDER BY count DESC LIMIT 10')
    return cursor.fetchall()

def get_top_requesters():
    cursor.execute('SELECT username, count FROM requesters ORDER BY count DESC LIMIT 10')
    return cursor.fetchall()            
    mention_counts.clear()
    original_sender_counts.clear()



def count_mentions_in_message(msg):
    for user in msg.mentions:
        update_helper_count(user.id, user.display_name, 1)

    for embed in msg.embeds:
        if embed.type == 'rich':
            mentions_from_embed = extract_mentions_from_embed(embed, msg.guild)
            for user_id, count in mentions_from_embed.items():
                user = msg.guild.get_member(int(user_id))
                if user:
                    update_helper_count(user.id, user.display_name, count)

def extract_original_senders(msg):
    for embed in msg.embeds:
        if embed.type == 'rich' and embed.author and embed.author.name:
            original_sender = discord.utils.get(msg.guild.members, name=embed.author.name)
            if original_sender:
                update_requester_count(original_sender.id, original_sender.display_name, 1)
        
        if embed.type == 'rich' and embed.fields:
            thank_you_field = next((field for field in embed.fields if field.name == "Thank You"), None)
            if thank_you_field:
                author_name = thank_you_field.value.split("from ")[-1].strip()
                original_sender = discord.utils.find(lambda m: m.name.lower() == author_name.lower(), msg.guild.members)
                if original_sender:
                    update_requester_count(original_sender.id, original_sender.display_name, 1)


def extract_mentions_from_embed(embed, guild):
    mention_counts = defaultdict(int)
    mention_pattern = re.compile(r'<@!?(\d+)>')

    if embed.description:
        mentions = mention_pattern.findall(embed.description)
        for user_id in mentions:
            mention_counts[user_id] += 1

    for field in embed.fields:
        mentions = mention_pattern.findall(field.value)
        for user_id in mentions:
            mention_counts[user_id] += 1

    return mention_counts


async def reset_database(ctx):
    cursor.execute('DELETE FROM helpers')
    cursor.execute('DELETE FROM requesters')
    conn.commit()
    await ctx.send("Database has been reset. Updating with latest data...")
    await update_database()
    await ctx.send("Database update complete.")

    
def get_mentions_from_text(text, guild):
    mention_pattern = re.compile(r'<@!?\d+>')
    mention_counts = defaultdict(int)
    mentions = mention_pattern.findall(text)
    for user_id in mentions:
        user = guild.get_member(int(user_id[2:-1]))
        if user:
            mention_counts[user.display_name] += 1
    return mention_counts

def get_member_display_name(guild, username):
    member = discord.utils.get(guild.members, name=username)
    return member.display_name if member else username

# Define the choices for the reason
reason_choices = [
    app_commands.Choice(name="UltraSpeaker", value="UltraSpeaker"),
    app_commands.Choice(name="Ultra Dailies", value="Ultra Dailies"),
    app_commands.Choice(name="Ultra Weeklies", value="Ultra Weeklies"),
    app_commands.Choice(name="Temple Shrine", value="Temple Shrine"),
    app_commands.Choice(name="Other", value="Other")
]

@client.tree.command(name="thx", description="Thank players and specify a reason")
@app_commands.describe(
    player1="First player (mandatory)",
    player2="Second player (optional)",
    player3="Third player (optional)",
    player4="Fourth player (optional)",
    player5="Fifth player (optional)",
    player6="Sixth player (optional)",
    player7="Seventh player (optional)",
    reason="Reason for thanks (mandatory)"
)
@app_commands.choices(reason=reason_choices)
async def thx(
    interaction: discord.Interaction,
    player1: discord.Member,
    reason: app_commands.Choice[str],
    player2: discord.Member = None,
    player3: discord.Member = None,
    player4: discord.Member = None,
    player5: discord.Member = None,
    player6: discord.Member = None,
    player7: discord.Member = None
):
    try:
        # Check if the user has recently posted in the trigger channel
        user_last_trigger_time = last_trigger_message.get(interaction.user.id)
        if not user_last_trigger_time or (datetime.now() - user_last_trigger_time) > timedelta(minutes=60):
            await interaction.response.send_message("You must ask for help first before using this command.", ephemeral=True)
            return

        # Check for self-thanking
        players = [player for player in [player1, player2, player3, player4, player5, player6, player7] if player]
        if interaction.user in players:
            await interaction.response.send_message("You cannot thank yourself.", ephemeral=True)
            return

        # Defer the response
        await interaction.response.defer(ephemeral=True)
        
        specific_channel = client.get_channel(SPECIFIC_CHANNEL_ID)
        if specific_channel:
            embed = discord.Embed(title="Thank You!", color=0x400080)
            embed.add_field(name="Thank You", value=f"Thank you from {interaction.user.name}", inline=False)
            embed.add_field(name="Reason", value=reason.value, inline=False)
            
            # Determine how many times to repeat the player mentions
            if reason.value == "UltraSpeaker":
                repeat_count = 3
            elif reason.value in ["Ultra Dailies", "Ultra Weeklies", "Temple Shrine"]:
                repeat_count = 2
            else:  # "Other"
                repeat_count = 1
            
            for _ in range(repeat_count):
                for i, player in enumerate(players, start=1):
                    embed.add_field(name=f"Player {i}", value=player.mention, inline=True)
                sent_message = await specific_channel.send(embed=embed)
                
                # Add a small delay and fetch the message again to ensure it's fully processed
                await asyncio.sleep(1)
                try:
                    sent_message = await specific_channel.fetch_message(sent_message.id)
                    await check_and_react_to_trigger_messages(sent_message)
                except discord.errors.NotFound:
                    print(f"Message {sent_message.id} not found after sending.")
                except Exception as e:
                    print(f"Error checking and reacting to message: {str(e)}")
                
                embed.clear_fields()
            
            # Use followup instead of response
            await interaction.followup.send("Thank you message has been sent successfully!", ephemeral=True)
        else:
            await interaction.followup.send("Specific channel not found.", ephemeral=True)
    except Exception as e:
        print(f"Error in thx command: {str(e)}")
        try:
            await interaction.followup.send("An error occurred while processing your command.", ephemeral=True)
        except:
            pass
@tasks.loop(minutes=30)
async def check_unverified_messages():
    now = datetime.now()
    for msg_id, timestamp in list(unverified_messages.items()):
        try:
            trigger_message = await client.get_channel(TRIGGER_CHANNEL_ID).fetch_message(msg_id)
            initial_emoji = discord.PartialEmoji(name=INITIAL_EMOJI_NAME, id=INITIAL_EMOJI_ID)

            # Check if the message already has the x_emoji or reaction_emoji
            has_x_emoji = any(reaction.emoji == discord.PartialEmoji(name=X_EMOJI_NAME, id=X_EMOJI_ID) for reaction in trigger_message.reactions)
            has_reaction_emoji = any(reaction.emoji == discord.PartialEmoji(name=REACTION_EMOJI_NAME, id=REACTION_EMOJI_ID) for reaction in trigger_message.reactions)

            if has_x_emoji or has_reaction_emoji:
                # Skip the message if it already has the x_emoji or reaction_emoji
                del unverified_messages[msg_id]
                continue

            if now - timestamp >= timedelta(minutes=60):
                await trigger_message.remove_reaction(initial_emoji, client.user)
                
                x_emoji = discord.PartialEmoji(name=X_EMOJI_NAME, id=X_EMOJI_ID)
                await trigger_message.add_reaction(x_emoji)
                del unverified_messages[msg_id]  # Remove from the unverified_messages dict
        except discord.errors.NotFound:
            print(f'Message with ID {msg_id} not found in trigger channel.')
            del unverified_messages[msg_id]  # Remove the message from the dictionary
        except discord.errors.HTTPException as e:
            print(f"Failed to modify reactions: {e}")
        except KeyError:
            print(f'Message with ID {msg_id} not found in unverified_messages dictionary.')

@client.tree.command(name="cancel", description="Cancel a message in the trigger channel by switching the initial emoji with the x emoji.")
async def cancel(interaction: discord.Interaction):
    try:
        # Replace these role IDs with the IDs of roles that are allowed to use this command
        allowed_role_ids = {1201111917213790218, 1192681906278518895, 1213396176058195988}

        # Check if the user has any of the allowed roles
        user_roles = {role.id for role in interaction.user.roles}
        if not allowed_role_ids.intersection(user_roles):
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return

        trigger_channel = client.get_channel(TRIGGER_CHANNEL_ID)
        if not trigger_channel:
            await interaction.response.send_message("Trigger channel not found.", ephemeral=True)
            return

        # Fetch messages in the trigger channel with the initial emoji
        messages_with_initial_emoji = []
        async for message in trigger_channel.history(limit=100):  # Adjust limit as needed
            has_initial_emoji = any(reaction.emoji == discord.PartialEmoji(name=INITIAL_EMOJI_NAME, id=INITIAL_EMOJI_ID) for reaction in message.reactions)
            if has_initial_emoji:
                messages_with_initial_emoji.append(message)

        if not messages_with_initial_emoji:
            await interaction.response.send_message("No messages with the initial emoji found.", ephemeral=True)
            return

        # Create a list of message options
        options = [
            discord.SelectOption(
                label=f"Message from {message.author.display_name}",
                description=message.content[:100],  # Limit description length
                value=str(message.id)
            )
            for message in messages_with_initial_emoji
        ]

        # Define the select menu
        class MessageSelect(discord.ui.Select):
            def __init__(self):
                super().__init__(placeholder="Select a message to cancel...", options=options)

            async def callback(self, interaction: discord.Interaction):
                selected_message_id = int(self.values[0])
                selected_message = discord.utils.get(messages_with_initial_emoji, id=selected_message_id)

                if selected_message:
                    # Remove the initial emoji and add the x emoji
                    initial_emoji = discord.PartialEmoji(name=INITIAL_EMOJI_NAME, id=INITIAL_EMOJI_ID)
                    x_emoji = discord.PartialEmoji(name=X_EMOJI_NAME, id=X_EMOJI_ID)

                    await selected_message.remove_reaction(initial_emoji, client.user)
                    await selected_message.add_reaction(x_emoji)

                    await interaction.response.send_message(f"Message from {selected_message.author.display_name} has been canceled.", ephemeral=True)
                else:
                    await interaction.response.send_message("Selected message not found.", ephemeral=True)

        # Create a view with the select menu
        view = discord.ui.View()
        view.add_item(MessageSelect())

        # Send the select menu to the user
        await interaction.response.send_message("Select a message to cancel:", view=view, ephemeral=True)

    except Exception as e:
        print(f"Error in cancel command: {str(e)}")
        await interaction.response.send_message("An error occurred while processing your command.", ephemeral=True)

@tasks.loop(minutes=60)
async def update_database():
    specific_channel = client.get_channel(SPECIFIC_CHANNEL_ID)
    if specific_channel:
        cursor.execute('DELETE FROM helpers')
        cursor.execute('DELETE FROM requesters')
        conn.commit()
        
        async for msg in specific_channel.history(limit=None):
            count_mentions_in_message(msg)
            extract_original_senders(msg)
        
        print("Database updated successfully.")

# Add a command to manually trigger database update
@client.tree.command(name="update_db", description="Manually update the database")
@app_commands.checks.has_permissions(administrator=True)  # Add a permission check
async def manual_update_db(interaction: discord.Interaction):
    try:
        await interaction.response.defer(ephemeral=True)
        await update_database()
        await interaction.followup.send("Database has been manually updated.", ephemeral=True)
    except Exception as e:
        print(f"Error in update_db command: {str(e)}")
        await interaction.followup.send("An error occurred while updating the database.", ephemeral=True)

@client.tree.command(name="reset_db", description="Reset and update the database")
@app_commands.checks.has_permissions(administrator=True)  # Add a permission check
async def reset_db_command(interaction: discord.Interaction):
    try:
        await interaction.response.defer(ephemeral=True)
        await reset_database(interaction)
        await interaction.followup.send("Database has been reset and updated.", ephemeral=True)
    except Exception as e:
        print(f"Error in reset_db command: {str(e)}")
        await interaction.followup.send("An error occurred while resetting the database.", ephemeral=True)

async def reset_database(interaction):  # Make this function async
    cursor.execute('DELETE FROM helpers')
    cursor.execute('DELETE FROM requesters')
    conn.commit()
    await interaction.followup.send("Database has been reset. Updating with latest data...")
    await update_database()
# ... (keep the rest of the code as is)
# Start the database update task when the bot is ready
@client.event
async def on_ready():
    print(f'Logged in as {client.user}')
    await client.tree.sync()
    check_unverified_messages.start()
    update_database.start()

# Don't forget to close the database connection when the bot shuts down
@client.event
async def on_shutdown():
    conn.close()

client.run(TOKEN)
